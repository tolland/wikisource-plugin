# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An IntelliJ Platform plugin that adds Wikitext language support (`.wt` / `.wiki` files) to IntelliJ IDEA, paired with a Python sidecar (`wtbot`) that fetches content from MediaWiki via pywikibot and exchanges it with the plugin through a shared SQLite database. For inspection purpose we also have a svelteKit based viewer app ./viewer which is not part of the main workflow but is convenient for inspection and debugging of state, and is used for out-of-band approval of edits.

## Code style

### Python

We are using modern python version 3.13 and above for generics, type aliases, better f-strings, and unpacking kwargs. please use modern python

Use of uv. The project is built in a environment which has a local pypi mirror
so uv.lock contains LAN local urls, so don't commit uv.lock to the repo.

Due to a bug in pycharm, please put file-based docstrings under the imports, so the imports are the first block in the page.

### Kotlin

Prefer a class per file structure for substantial implementations. This does not apply for wholly owned or dataclasses which are associated with a main class.

## Build and run commands

### Kotlin/Gradle (plugin)

```bash
./gradlew build                        # full build
./gradlew runIde                       # launch sandbox IDE with test-project/ opened
./gradlew test                         # all tests
./gradlew :wikitext-core:test          # tests for core module only
./gradlew generateLexer generateParser # regenerate from .flex / .bnf (wikitext-core only)
```

### Python sidecar (wtbot)

Dependencies are managed with `uv` (`pyproject.toml` + `uv.lock`).

```bash
uv run fastapi dev src-py/wtbot/main.py   # start FastAPI dev server
uv run pytest                              # run Python tests
```

## Architecture

### Gradle modules

| Module | Purpose |
|--------|---------|
| `wikitext-core` | Language fundamentals: lexer, parser, PSI types, facet |
| `wikitext-ui` | IDE UI: syntax highlighting, annotator, tool window, VFS, structure view, split-editor preview |
| `src-py` | Python sidecar (`wtbot` package) |

The root `build.gradle.kts` assembles the plugin and launches the sandbox IDE; `wikitext-ui` depends on `wikitext-core`.

### Lexer and parser (GrammarKit)

- **Lexer**: `wikitext-core/src/main/kotlin/…/lexer/WikitextLexer.flex` → JFlex generates Java into `src/main/gen/…/lexer/`
- **Parser**: `wikitext-core/src/main/kotlin/…/parser/Wikitext.bnf` → Grammar-Kit generates Java/Kotlin into `src/main/gen/…/psi/`

Generated code is **not hand-edited**. After changing `.flex` or `.bnf` run `generateLexer` / `generateParser`.

**Critical constraint**: every token name declared in `Wikitext.bnf`'s `tokens=[...]` block must be distinct from every rule name in the same file. A collision causes Grammar-Kit to silently replace the lexer's leaf token with a rule's composite `WtElementType` — this was a real production bug (affected `HEADING_LINE`, `LINK_TARGET`, `TEMPLATE_NAME`).

The lexer uses a frame/state stack to disambiguate context-dependent tokens (e.g. `TEMPLATE_PIPE` vs `LINK_PIPE` vs `TABLE_CELL_SEP` are all `|`, decided by `pipeTokenForContext()` based on the top-of-stack frame kind).

### Virtual file system

`WtVirtualFileSystem` implements the `wikisource://` protocol. Currently serves a hardcoded in-memory dummy tree (one `Index:` with a few `Page:` children). The tool window (`MyToolWindowFactory`) follows the DataGrip Database Explorer pattern: a custom tree in a side panel, opening real editor tabs via `FileEditorManager` on double-click, which applies the full PSI/lexer/annotator stack.

Real SQLite-backed VFS is planned — the schema is defined by the SQLModel classes in `src-py/wtbot/sqlmodel/` (see `src-py/DESIGN.md`).

### SQLite IPC contract

The plugin (Kotlin/JDBC) and the Python sidecar communicate exclusively through a shared SQLite database (`database.db`). Both sides **must** set these pragmas on every connection:

```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

Transaction handling is the driver's normal deferred style — an earlier eager `BEGIN IMMEDIATE`-on-every-transaction rule held the write lock across whole requests, proved unreliable, and was reverted. The `FetchRequest` table is the job queue: the plugin inserts rows, pywikibot updates `status` as it works, child requests fan out from parent requests via `parent_pk`. The `Commit` table is the outbound log for edits pushed back to the wiki; `EditJournal` is the local per-save transaction log.

### Python sidecar (`wtbot`)

- `src-py/wtbot/main.py` — FastAPI app factory (`create_app`)
- `src-py/wtbot/db.py` — SQLite engine + WAL/busy-timeout pragma discipline
- `src-py/wtbot/sqlmodel/` — SQLModel ORM models, the **single source of truth** for the schema (`Site`, `Namespace`, `Page`, `Transclusion`, `FetchRequest`, `EditJournal`, `Commit`)
- `src-py/wtbot/api/` — FastAPI routers (`health`, `sites`, …)
- `src-py/DESIGN.md` — backend operations & data-model design
- `src-py/tests/` — pytest suite (`uv run --extra dev pytest`)

### Tests

Tests live under `wikitext-core/src/test/`. Two base classes drive data-driven tests:

- `WtLexerTestCase` — lexer tests: each `testFooBar()` method loads `src/test/testData/simple/fooBar.wt` as input and diffs against `fooBar.txt`
- `WtParsingTextCase` — parser tests: loads `.wt` input, diffs against `.parse.txt` expected tree

The `LEXER_DEBUG=true` system property is set during `./gradlew test` to enable verbose lexer output.

### Target platform

IntelliJ IDEA **2026.2 RC**, exact build **262.8665.176** (`intellijPlatformVersion` in `gradle.properties`). The sandbox config in `sandbox-config/` is copied into the sandbox on each `prepareSandbox` task run.
