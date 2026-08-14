# CLAUDE.md

@AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An IntelliJ Platform plugin that adds Wikitext language support (`.wt` / `.wiki` files) to IntelliJ IDEA, paired with a Python sidecar (`wtbot`) that fetches content from MediaWiki via pywikibot and exchanges it with the plugin exclusively through a FastAPI HTTP contract backed by a shared SQLite database. There is also a SvelteKit app (`./viewer`) that is not part of the main workflow but is convenient for inspecting/debugging sidecar state and for out-of-band approval of edits.

## Documentation

`docs/` is organised by purpose, indexed in `docs/README.md`: `todo/` (actionable unfinished work, in priority order), `design/` (relevant but unscheduled designs), `reference/` (how the system behaves today — architecture, operational notes, empirical findings), `done/` (completed plans, retained for the "why is it like this?" question). Backend data model and the fetch/edit/commit contract stay in `src-py/DESIGN.md`.

## Code style

### Python

We are using modern python version 3.13 and above for generics, type aliases, better f-strings, and unpacking kwargs. Please use modern python. Favor typed classes and avoid dict-based data passing.

Use of `uv`. The project is built in an environment which has a local pypi mirror, so `uv.lock` contains LAN-local urls — don't commit `uv.lock` to the repo.

Due to a bug in PyCharm, please put file-based docstrings under the imports, so the imports are the first block in the page.

### Kotlin

Prefer a class per file structure for substantial implementations. This does not apply for wholly-owned or dataclasses which are associated with a main class.

## Build and run commands

### Kotlin/Gradle (plugin)

Always use a workspace-local Gradle user home in this repo — set `GRADLE_USER_HOME` to a project-local directory before invoking Gradle:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew build          # full build
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew runIde          # launch sandbox IDE
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew test            # all tests
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext-core:test   # single module's tests
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew generateLexer generateParser  # regenerate from .flex / .bnf (wikitext-core only)
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew check           # build + tests + spotless, run by the pre-commit hook
```

The sandbox's wtbot sidecar can be chosen per launch, so a session can be pointed at the docker harness instead of the workstation sidecar without editing settings by hand:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew runIde -PwtbotBaseUrl=http://127.0.0.1:18584 [-PwtbotTimeoutSeconds=30]
```

These become the `wtbot.baseUrl` / `wtbot.timeoutSeconds` system properties (`WTBOT_BASE_URL` / `WTBOT_TIMEOUT_SECONDS` env vars work too, for a non-sandbox IDE). They seed the setting at every launch rather than only on a fresh sandbox, and the running IDE can still be moved to another backend from Settings → Tools → WTBot (VFS backend) without restarting.

`runIde` opens a sandbox IDE against `../test-project` (a sibling directory of this repo root, not inside it — create it if it doesn't exist locally). The sandbox config in `sandbox-config/` (editor, look-and-feel, trusted paths, log categories) is copied into the sandbox on every `prepareSandbox` run. The exact target IDE build is pinned in `gradle.properties` (`intellijPlatformVersion`) so Gradle never silently re-resolves a newer RC.

A single test class/method can be run the normal Gradle way, e.g. `GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext-core:test --tests "org.limepepper.lang.wikitext.lexer.WtLexerTest.testFooBar"`.

### Python sidecar (wtbot)

Dependencies are managed with `uv` (`pyproject.toml` + `uv.lock`).

```bash
uv run fastapi dev src-py/wtbot/main.py --port 18564   # start FastAPI dev server (dev-convention port, see docs/reference/logging.md)
uv run pytest                              # run Python tests (uses pythonpath=src-py, testpaths=src-py/tests)
uv run pytest src-py/tests/test_fetch.py -k some_case  # single test
uv run pytest -m slow                      # incl. the docker-backed harness suites (deselected by default)

# The two-wiki sync harness. Both wikis seed themselves from the same compose
# anchor (SEED_DUMPS/SEED_SCANS), so the pair starts converged; `--wait` blocks
# until seeding is done. `up`/`status`/`down` is a convenience wrapper on it.
docker compose -f compose.seeded.yml --profile pair up -d --wait
PYTHONPATH=src-py/tests uv run python -m wiki_harness status

# ...plus the wtbot API itself (compose.wtbot.yml overlays either base), so the
# whole system is reachable over HTTP instead of only from inside pytest.
# SQLite lives on a disposable volume; WTBOT_RESET_DB=1 empties it without
# rebuilding the wikis. Served on $WTBOT_PORT (default 18583).
docker compose -f compose.seeded.yml -f compose.wtbot.yml \
    --profile pair --profile api up -d --wait
PYTHONPATH=src-py/tests uv run python -m wiki_harness up --api
uv run ruff check --fix                    # lint (mirrors the pre-commit hook)
uv run black .                             # format (mirrors the pre-commit hook)
```

`pre-commit` (`.pre-commit-config.yaml`) runs `ruff check --fix` + `black` on pre-commit, and `./gradlew check` on pre-push — both sides of the repo are gated by the same hooks.

Wiki access in tests is either faked in-memory (`FakeWikiClient`, the default — fast, no network) or live-fire against the docker harness wikis (`@pytest.mark.slow`, needs `--runslow` and a docker daemon). There is no recorded-cassette layer: recordings drifted out of date against pywikibot and could only be refreshed from a machine with access to both wikis, so a stale recording failed on requests our code never made.

### Viewer (SvelteKit, debug UI only)

```bash
cd viewer && npm run dev       # dev server
cd viewer && npm run check     # svelte-check
cd viewer && npm run build
```

## Architecture

### Gradle modules

| Module | Purpose |
|--------|---------|
| `wikitext-core` | Language fundamentals: lexer, parser, PSI types, facet |
| `wikitext-vfs` | `wikisource://` virtual file system + the `VfsBackend` client for the wtbot HTTP contract |
| `wikitext-ui` | IDE UI: syntax highlighting, annotator, tool window, structure view, split-editor preview |
| `src-py` | Python sidecar (`wtbot` package) |

The root `build.gradle.kts` assembles the plugin (`pluginModule` for each of `wikitext-core`, `wikitext-vfs`, `wikitext-ui`) and launches the sandbox IDE; `wikitext-vfs` and `wikitext-ui` both depend on `wikitext-core`.

### Lexer and parser (GrammarKit)

- **Lexer**: `wikitext-core/src/main/kotlin/…/lexer/WikitextLexer.flex` → JFlex generates Java into `src/main/gen/…/lexer/`
- **Parser**: `wikitext-core/src/main/kotlin/…/parser/Wikitext.bnf` → Grammar-Kit generates Java/Kotlin into `src/main/gen/…/psi/`

Generated code is **not hand-edited**. After changing `.flex` or `.bnf` run `generateLexer` / `generateParser`.

**Critical constraint**: every token name declared in `Wikitext.bnf`'s `tokens=[...]` block must be distinct from every rule name in the same file. A collision causes Grammar-Kit to silently replace the lexer's leaf token with a rule's composite `WtElementType` — this was a real production bug (affected `HEADING_LINE`, `LINK_TARGET`, `TEMPLATE_NAME`).

The lexer uses a frame/state stack to disambiguate context-dependent tokens (e.g. `TEMPLATE_PIPE` vs `LINK_PIPE` vs `TABLE_CELL_SEP` are all `|`, decided by `pipeTokenForContext()` based on the top-of-stack frame kind).

`wikitext-core/src/main/kotlin/…/lexer/` and `…/parser/` also contain `.flex`/`.bnf` grammars for several embedded/adjacent languages (Handlebars, Markdown, Makefile, Prisma, Dart, raw HTML/XML) used for host-language interop inside wikitext content — these follow the same "generated code, not hand-edited" rule.

### Virtual file system (`wikitext-vfs`)

`WtVirtualFileSystem` implements the `wikisource://` protocol and is backed by the `VfsBackend` interface (`wikitext-vfs/.../vfs/backend/VfsBackend.kt`), which talks to the wtbot FastAPI sidecar over HTTP — `HttpVfsBackend` is the real implementation, `FakeVfsBackend` is used for tests/offline.

Which sidecar that is lives in `WtbotAppSettings` (application-scoped: wtbot itself mediates between wikis, so one sidecar serves every project, and the VFS is an app singleton). `WtVfsService` owns the live backend and *replaces* it — `HttpVfsBackend` is immutable — when the settings change, so callers must keep reading `WtVfsService.instance.backend` per operation rather than holding a reference. A base-URL change also runs `WtBackendSwitcher`: prompt about unsaved `wikisource://` documents while the old sidecar is still theirs to save to, drop every cached file's content/children, re-stat them against the new backend, close editors on paths it doesn't have, reload the ones it does, then fire `WtVfsService.BACKEND_SWITCHED` for the tool window. Cached `WtVirtualFile` instances are never evicted wholesale — the VFS contract requires one instance per path, and editors/tree nodes hold them — only paths absent from the new backend are evicted and marked invalid. A timeout-only change just swaps the client. `VfsBackend` covers stat (single + bulk), list, read, write (with `baseRevid` conflict detection), live preview rendering, ProofreadPage page navigation, and reference-scan image URLs. The tool window (`MyToolWindowFactory`, in `wikitext-ui`) follows the DataGrip Database Explorer pattern: a custom tree in a side panel, opening real editor tabs via `FileEditorManager` on double-click, which applies the full PSI/lexer/annotator stack.

### Split-editor preview (`wikitext-ui/.../preview/`)

`WtEditorWithPreview` pairs the raw wikitext editor with `WtRenderPreviewBrowser`, a live HTML preview rendered server-side. Rather than parsing wikitext client-side or hitting MediaWiki's `action=parse` directly from Kotlin, the preview is proxied through wtbot (`POST /preview/render`, see `src-py/wtbot/api/preview.py`) so that content-model awareness (plain `wikitext` vs ProofreadPage's `proofread-page`), credentials, and the LAN CA bundle all stay server-side. See `docs/reference/preview-design.md` for the full rationale and the two rejected alternatives (classic `EditPage` form-post preview, Parsoid). `WtProofreadPageEditor`/`WtProofreadIndexEditor` add ProofreadPage-specific chrome (page-quality header, reference scan pane via `ReferenceImagePane`, prev/next page navigation via `WtPageNavToolbar`).

### SQLite IPC contract

The plugin (Kotlin/JDBC, via `wikitext-vfs`'s HTTP backend) and the Python sidecar communicate through wtbot's FastAPI HTTP endpoints, with SQLite (`database.db`) as the sidecar's own storage. Both sides that touch the database directly **must** set these pragmas on every connection:

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

Transaction handling is the driver's normal deferred style — an earlier eager `BEGIN IMMEDIATE`-on-every-transaction rule held the write lock across whole requests, proved unreliable, and was reverted; under WAL, readers need no lock at all. The `FetchRequest` table is the job queue: the plugin submits fetch requests via the sidecar, pywikibot updates `status` as it works, child requests fan out from parent requests via `parent_pk` (e.g. an `Index:` fetch fans out to its `Page:` children). The `Commit` table is the outbound log for edits pushed back to the wiki; `EditJournal` is the local per-save transaction log — a VFS `write` never touches the wiki directly, it only appends to the journal and marks the page dirty; pushing to the wiki is a separate, explicit `commit`. See `src-py/DESIGN.md` for the full fetch/edit/commit model, the ProofreadPage content model (roles resolved from per-site `siteinfo` rather than hardcoded namespace ids — `Page`/`Index` numeric ids differ between en.wikisource.org and a fresh ProofreadPage install), and the planned cross-wiki `RevisionLink` correspondence model.

### Python sidecar (`wtbot`)

- `src-py/wtbot/main.py` — FastAPI app factory (`create_app`)
- `src-py/wtbot/db.py` — SQLite engine + WAL/busy-timeout pragma discipline
- `src-py/wtbot/model/` — SQLModel ORM models, the **single source of truth** for the schema (`Site`, `Namespace`, `Page`, `Transclusion`, `FetchRequest`, `EditJournal`, `Commit`, …)
- `src-py/wtbot/api/` — FastAPI routers: `fetch` (cache-fill job queue + `/fetch/drain`), `vfs` (read/write/list/stat for the plugin's VFS), `commit` (push-back to the wiki), `preview` (server-rendered live preview: wikitext → HTML), `reference_image` (the scan being transcribed — ProofreadPage's `imageforpage`, served from `/reference-image`), `page_nav`/`page_meta` (ProofreadPage navigation/metadata), `namespace`, `sites` (registration + per-site credentials), `edit_journal`, `viewer` (backs the SvelteKit debug app), `health`

A wiki is **registered before anything fetches from it** and addressed by its unique `label` thereafter; nothing creates a Site implicitly. Fetching is also decoupled from enqueueing — `POST /fetch` queues, `POST /fetch/drain` (or `wtbot drain`) does the throttled work:

wtbot **authenticates by default**: a site with no credential is refused at fetch time (409) and at client construction. Not because the published rate-limit tiers demand it — a compliant unauthenticated client gets the same 200 req/min — but because this backs an editor (commits need an account) and Wikimedia's CDN refuses unauthenticated traffic unevenly per IP range without documenting it. `WTBOT_ALLOW_ANONYMOUS=1` lifts the requirement for reading a public wiki from a workstation, and logs every use.

```bash
uv run wtbot site add --label local --family mywikisource --code en \
    --api-url https://wikisource-debian-13.lan/w/api.php \
    --username Admin --password ... [--bot-password-suffix wtbot]
# or attach the account afterwards:
uv run wtbot site-credential add --label local --username Admin --password ...
uv run wtbot fetch-page "Index:Some book.djvu" --label local   # queues
uv run wtbot drain                                             # fetches
uv run wtbot drain --status                                    # queue depth
```

`--label` and `--base-url` are TyperDI dependencies (`src-py/wtbot/cli/deps.py`), so they appear on every command that declares them rather than being dug out of `ctx.parent.params`; `WTBOT_SITE_LABEL` sets the default label for a shell session.
- `src-py/wtbot/wiki/` — the injectable wiki-access seam: `WikiSettings` (config), `configure_pywikibot()` (programmatic config, no on-disk `user-config.py`), `WikiClient` protocol with `PywikibotClient` (real) and `FakeWikiClient` (in-memory, no pywikibot import) implementations, `dispatch.py` (classifies a fetched title as `FILE`/`PROOFREAD_INDEX`/`PROOFREAD_PAGE`/`WIKITEXT` from namespace role + content_model)
- `src-py/wtbot/vfs/` — VFS-surface implementation backing the `/vfs` router
- `src-py/wtbot/worker.py` — the fetch worker (`run_pending`) that drains the `FetchRequest` queue; today invoked inline by `POST /fetch` rather than as a background loop
- `src-py/DESIGN.md` — backend operations & data-model design (read this before touching the fetch/VFS/commit contract)
- `src-py/tests/` — pytest suite (`uv run pytest`); wiki calls use `FakeWikiClient` by default, or a real wiki from the docker harness in the `@pytest.mark.slow` suites

### Tests

Tests live under `wikitext-core/src/test/`, `wikitext-vfs/src/test/`, and `wikitext-ui/src/test/`. Two base classes drive data-driven tests in `wikitext-core`:

- `WtLexerTestCase` — lexer tests: each `testFooBar()` method loads `src/test/testData/simple/fooBar.wt` as input and diffs against `fooBar.txt`
- `WtParsingTextCase` — parser tests: loads `.wt` input, diffs against `.parse.txt` expected tree

The `LEXER_DEBUG=true` system property is set during `./gradlew test` to enable verbose lexer output.

### Target platform

IntelliJ IDEA **2026.2 RC**, exact build **262.8665.176** (`intellijPlatformVersion` in `gradle.properties`). The sandbox config in `sandbox-config/` is copied into the sandbox on each `prepareSandbox` task run.
