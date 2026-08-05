# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An IntelliJ Platform plugin that adds Wikitext language support (`.wt` / `.wiki` files) to IntelliJ IDEA, paired with a Python sidecar (`wtbot`) that fetches content from MediaWiki via pywikibot and exchanges it with the plugin exclusively through a FastAPI HTTP contract backed by a shared SQLite database. There is also a SvelteKit app (`./viewer`) that is not part of the main workflow but is convenient for inspecting/debugging sidecar state and for out-of-band approval of edits.

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

`runIde` opens a sandbox IDE against `../test-project` (a sibling directory of this repo root, not inside it — create it if it doesn't exist locally). The sandbox config in `sandbox-config/` (editor, look-and-feel, trusted paths, log categories) is copied into the sandbox on every `prepareSandbox` run. The exact target IDE build is pinned in `gradle.properties` (`intellijPlatformVersion`) so Gradle never silently re-resolves a newer RC.

A single test class/method can be run the normal Gradle way, e.g. `GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext-core:test --tests "org.limepepper.lang.wikitext.lexer.WtLexerTest.testFooBar"`.

### Python sidecar (wtbot)

Dependencies are managed with `uv` (`pyproject.toml` + `uv.lock`).

```bash
uv run fastapi dev src-py/wtbot/main.py   # start FastAPI dev server
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

Wiki access in tests goes through `vcrpy` cassettes under `src-py/tests/cassettes/` rather than live network calls; see `WikiClient`/`FakeWikiClient` below for the non-cassette fake path.

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

`WtVirtualFileSystem` implements the `wikisource://` protocol and is backed by the `VfsBackend` interface (`wikitext-vfs/.../vfs/backend/VfsBackend.kt`), which talks to the wtbot FastAPI sidecar over HTTP — `HttpVfsBackend` is the real implementation, `FakeVfsBackend` is used for tests/offline. `VfsBackend` covers stat (single + bulk), list, read, write (with `baseRevid` conflict detection), live preview rendering, ProofreadPage page navigation, and reference-scan image URLs. The tool window (`MyToolWindowFactory`, in `wikitext-ui`) follows the DataGrip Database Explorer pattern: a custom tree in a side panel, opening real editor tabs via `FileEditorManager` on double-click, which applies the full PSI/lexer/annotator stack.

### Split-editor preview (`wikitext-ui/.../preview/`)

`WtEditorWithPreview` pairs the raw wikitext editor with `WtRenderPreviewBrowser`, a live HTML preview rendered server-side. Rather than parsing wikitext client-side or hitting MediaWiki's `action=parse` directly from Kotlin, the preview is proxied through wtbot (`POST /preview/render`, see `src-py/wtbot/api/preview.py`) so that content-model awareness (plain `wikitext` vs ProofreadPage's `proofread-page`), credentials, and the LAN CA bundle all stay server-side. See `docs/preview-design.md` for the full rationale and the two rejected alternatives (classic `EditPage` form-post preview, Parsoid). `WtProofreadPageEditor`/`WtProofreadIndexEditor` add ProofreadPage-specific chrome (page-quality header, reference scan pane via `ReferenceImagePane`, prev/next page navigation via `WtPageNavToolbar`).

### SQLite IPC contract

The plugin (Kotlin/JDBC, via `wikitext-vfs`'s HTTP backend) and the Python sidecar communicate through wtbot's FastAPI HTTP endpoints, with SQLite (`database.db`) as the sidecar's own storage. Both sides that touch the database directly **must** set these pragmas on every connection:

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

Transaction handling is the driver's normal deferred style — an earlier eager `BEGIN IMMEDIATE`-on-every-transaction rule held the write lock across whole requests, proved unreliable, and was reverted; under WAL, readers need no lock at all. The `FetchRequest` table is the job queue: the plugin submits fetch requests via the sidecar, pywikibot updates `status` as it works, child requests fan out from parent requests via `parent_pk` (e.g. an `Index:` fetch fans out to its `Page:` children). The `Commit` table is the outbound log for edits pushed back to the wiki; `EditJournal` is the local per-save transaction log — a VFS `write` never touches the wiki directly, it only appends to the journal and marks the page dirty; pushing to the wiki is a separate, explicit `commit`. See `src-py/DESIGN.md` for the full fetch/edit/commit model, the ProofreadPage content model (roles resolved from per-site `siteinfo` rather than hardcoded namespace ids — `Page`/`Index` numeric ids differ between en.wikisource.org and a fresh ProofreadPage install), and the planned cross-wiki `RemoteLink` correspondence model.

### Python sidecar (`wtbot`)

- `src-py/wtbot/main.py` — FastAPI app factory (`create_app`)
- `src-py/wtbot/db.py` — SQLite engine + WAL/busy-timeout pragma discipline
- `src-py/wtbot/model/` — SQLModel ORM models, the **single source of truth** for the schema (`Site`, `Namespace`, `Page`, `Transclusion`, `FetchRequest`, `EditJournal`, `Commit`, …)
- `src-py/wtbot/api/` — FastAPI routers: `fetch` (cache-fill job queue), `vfs` (read/write/list/stat for the plugin's VFS), `commit` (push-back to the wiki), `preview` (server-rendered live preview), `page_nav`/`page_meta`/`page_image` (ProofreadPage navigation/metadata/reference images), `namespace`, `sites`, `edit_journal`, `viewer` (backs the SvelteKit debug app), `health`
- `src-py/wtbot/wiki/` — the injectable wiki-access seam: `WikiSettings` (config), `configure_pywikibot()` (programmatic config, no on-disk `user-config.py`), `WikiClient` protocol with `PywikibotClient` (real) and `FakeWikiClient` (in-memory, no pywikibot import) implementations, `dispatch.py` (classifies a fetched title as `FILE`/`PROOFREAD_INDEX`/`PROOFREAD_PAGE`/`WIKITEXT` from namespace role + content_model)
- `src-py/wtbot/vfs/` — VFS-surface implementation backing the `/vfs` router
- `src-py/wtbot/worker.py` — the fetch worker (`run_pending`) that drains the `FetchRequest` queue; today invoked inline by `POST /fetch` rather than as a background loop
- `src-py/DESIGN.md` — backend operations & data-model design (read this before touching the fetch/VFS/commit contract)
- `src-py/tests/` — pytest suite (`uv run pytest`); wiki calls are mocked either via `vcrpy` cassettes (`src-py/tests/cassettes/`) or `FakeWikiClient`

### Tests

Tests live under `wikitext-core/src/test/`, `wikitext-vfs/src/test/`, and `wikitext-ui/src/test/`. Two base classes drive data-driven tests in `wikitext-core`:

- `WtLexerTestCase` — lexer tests: each `testFooBar()` method loads `src/test/testData/simple/fooBar.wt` as input and diffs against `fooBar.txt`
- `WtParsingTextCase` — parser tests: loads `.wt` input, diffs against `.parse.txt` expected tree

The `LEXER_DEBUG=true` system property is set during `./gradlew test` to enable verbose lexer output.

### Target platform

IntelliJ IDEA **2026.2 RC**, exact build **262.8665.176** (`intellijPlatformVersion` in `gradle.properties`). The sandbox config in `sandbox-config/` is copied into the sandbox on each `prepareSandbox` task run.
