-- =========================================================================
-- Wikisource plugin <-> pywikibot SQLite contract
-- =========================================================================
-- Mandatory pragmas -- BOTH processes must set these on EVERY connection,
-- not just once on the file. journal_mode is a file property and persists;
-- busy_timeout and BEGIN IMMEDIATE discipline are per-connection and must
-- be set by each process for itself.
--
--   PRAGMA journal_mode = WAL;
--   PRAGMA busy_timeout = 5000;
--   -- and wrap any write in BEGIN IMMEDIATE ... COMMIT rather than bare
--   -- BEGIN, on both the Kotlin/JDBC side and the Python sqlite3 side.
--
-- Check bundled SQLite version on both sides against 3.51.3+ (WAL-reset
-- bug fix) before relying on this topology under real concurrent writes.
-- =========================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- -------------------------------------------------------------------------
-- sites: one row per MediaWiki instance (en.wikisource.org, local Docker).
-- Authority segment used in wikisource:// VFS paths keys off `host`.
-- -------------------------------------------------------------------------
CREATE TABLE sites (
    site_id     INTEGER PRIMARY KEY,
    host        TEXT NOT NULL UNIQUE,      -- 'en.wikisource.org', 'wikisource-debian-13.lan'
    api_url     TEXT NOT NULL,             -- full action=... endpoint
    label       TEXT NOT NULL,             -- human-readable, for UI ("Local", "en.wikisource")
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- -------------------------------------------------------------------------
-- pages: one row per (site, title) -- covers mainspace, Index:, Page:,
-- Book:, Talk:, everything. namespace discriminates shape; type-specific
-- columns are nullable and only meaningful for their namespace. One table
-- (not three) because "search/replace across everything" is a core use
-- case and that wants a single scan, not a UNION across tables.
--
-- (site_id, title) is the natural key -- pageid is wiki-local and not
-- comparable across two independently-running instances, which is exactly
-- why this can't just be `pageid INTEGER PRIMARY KEY`.
-- -------------------------------------------------------------------------
CREATE TABLE pages (
    page_pk         INTEGER PRIMARY KEY,
    site_id         INTEGER NOT NULL REFERENCES sites(site_id),
    title           TEXT NOT NULL,             -- full title incl. namespace prefix, e.g.
                                                -- 'Page:The principles...(Hertz, 1894).pdf/171'
    namespace       INTEGER NOT NULL,          -- 0=main, 104=Page, 106=Index (check site's actual ns map)

    -- Remote identity / revision state -- this IS the conflict token, not
    -- separate metadata. `revid` + `remote_timestamp` are what gets sent
    -- back to the API as basetimestamp on save; a save that doesn't match
    -- what the server currently has is a real edit conflict, not a bug.
    pageid          INTEGER,                   -- wiki-local page pk, null until first fetch
    revid           INTEGER,                   -- revision pk as of last fetch
    remote_timestamp TEXT,                     -- MediaWiki revision timestamp (ISO 8601, UTC)
    contributor     TEXT,                      -- username of that revision's author
    comment         TEXT,                      -- edit summary of that revision
    sha1            TEXT,                      -- MediaWiki's content hash, cheap change-detection

    -- Local editing state
    body            TEXT,                      -- raw wikitext, null until fetched
    local_modified_at TEXT,                    -- when THIS ROW last changed locally; distinct
                                                -- from remote_timestamp on purpose -- conflating
                                                -- these is the exact bug class flagged earlier.
                                                -- This is what VirtualFile.getTimeStamp() reads,
                                                -- and what the IDE-side poller diffs against.
    dirty           INTEGER NOT NULL DEFAULT 0, -- 1 = local body differs from last-fetched revid

    -- Page:-namespace specific (null for other namespaces)
    index_title     TEXT,                      -- which Index: this Page belongs to
    page_number     INTEGER,                   -- numeric page-in-index, parsed from title suffix
    quality_level   INTEGER,                   -- ProofreadPage <pagequality level="N"/>, 0-4

    -- Index:-namespace specific (null for other namespaces)
    file_ref        TEXT,                      -- path/identifier of the backing PDF/DjVu on disk
    page_count      INTEGER,                   -- total pages per the Index's <pagelist>

    fetch_status    TEXT NOT NULL DEFAULT 'unfetched'
                        CHECK (fetch_status IN ('unfetched','pending','fetching','done','error')),
    fetch_error     TEXT,                      -- last error message, if fetch_status='error'

    UNIQUE (site_id, title)
);

CREATE INDEX idx_pages_site_namespace ON pages(site_id, namespace);
CREATE INDEX idx_pages_index_title    ON pages(site_id, index_title);
CREATE INDEX idx_pages_local_mod      ON pages(local_modified_at);
CREATE INDEX idx_pages_dirty          ON pages(dirty) WHERE dirty = 1;

-- Optional: FTS5 for "search/replace across the whole work" -- one of the
-- concrete stated goals. Contentless-rowid-pointer table to avoid storing
-- the body twice; rebuild via triggers or an explicit reindex step.
CREATE VIRTUAL TABLE pages_fts USING fts5(title, body, content='pages', content_rowid='page_pk');

-- -------------------------------------------------------------------------
-- transclusions: mainspace pages that pull in Page: content via
-- <pages index="..." from="N" to="M" />. Needed for "fetch the Index plus
-- any books that reference it via transclusion" and for invalidating a
-- mainspace page's rendered view when a constituent Page: changes.
-- -------------------------------------------------------------------------
CREATE TABLE transclusions (
    transclusion_id INTEGER PRIMARY KEY,
    site_id         INTEGER NOT NULL REFERENCES sites(site_id),
    source_page_pk  INTEGER NOT NULL REFERENCES pages(page_pk),  -- the mainspace page
    index_title     TEXT NOT NULL,             -- target Index: title
    from_page       INTEGER NOT NULL,
    to_page         INTEGER NOT NULL
);

CREATE INDEX idx_transclusions_index ON transclusions(site_id, index_title);

-- -------------------------------------------------------------------------
-- fetch_requests: the queue. Plugin INSERTs, pywikibot UPDATEs status as
-- it works, optionally fanning out into child requests as it discovers
-- structure (e.g. an Index request fans out into N per-page requests once
-- the page list is known) -- parent_request_id lets the plugin watch
-- aggregate progress on the ONE request it made without knowing about the
-- fan-out. This is the entire IPC mechanism: no dbus/MQTT, just rows.
-- -------------------------------------------------------------------------
CREATE TABLE fetch_requests (
    request_id      INTEGER PRIMARY KEY,
    site_id         INTEGER NOT NULL REFERENCES sites(site_id),
    parent_request_id INTEGER REFERENCES fetch_requests(request_id),
    target_title    TEXT NOT NULL,             -- what to fetch (Index:, Page:, or mainspace title)
    request_kind    TEXT NOT NULL
                        CHECK (request_kind IN ('index','page','transclusion_scan','single')),
    depth           INTEGER NOT NULL DEFAULT 0, -- 0 = just this page; >0 = include linked pages
    priority        INTEGER NOT NULL DEFAULT 0, -- higher = sooner; lets "open this now" jump a queue
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','in_progress','done','error','cancelled')),
    progress_done   INTEGER NOT NULL DEFAULT 0, -- units completed (e.g. pages fetched so far)
    progress_total  INTEGER,                    -- units expected, null until known
    error_message   TEXT,
    requested_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_fetch_requests_status ON fetch_requests(status, priority DESC, requested_at);
CREATE INDEX idx_fetch_requests_parent ON fetch_requests(parent_request_id);

-- -------------------------------------------------------------------------
-- commits: outbound side -- one row per attempted push back to the wiki.
-- Kept as a log (not just overwriting pages.revid in place) so a rejected
-- edit-conflict attempt is visible/retriable rather than silently lost,
-- and so the plugin can show "this save failed, here's why" after the
-- fact rather than only at the moment of the synchronous call.
-- -------------------------------------------------------------------------
CREATE TABLE commits (
    commit_id       INTEGER PRIMARY KEY,
    page_pk         INTEGER NOT NULL REFERENCES pages(page_pk),
    base_revid      INTEGER NOT NULL,          -- revid the edit was based on (the conflict token)
    submitted_body  TEXT NOT NULL,
    comment         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','success','conflict','error')),
    result_revid    INTEGER,                   -- new revid on success
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_commits_page   ON commits(page_pk);
CREATE INDEX idx_commits_status ON commits(status) WHERE status = 'pending';
