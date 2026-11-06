# Wikitext and Wikisource plugins for IntelliJ

This repository builds two IntelliJ Platform plugins:

| Plugin | ID | What it does |
|---|---|---|
| **Wikitext Language** | `org.limepepper.lang.wikitext` | Local `.wt` / `.wiki` editing: lexer, parser, syntax highlighting, annotators, structure view, live templates, Surround With and bold/italic toggles. Needs no network service. |
| **Wikisource** | `org.limepepper.wikisource` | Remote editing against MediaWiki/Wikisource: the `wikisource-wtbot://` filesystem, the Wikisource browser, ProofreadPage editors with live preview and reference scans, page navigation, scan annotation and OCR review. Requires the Wikitext Language plugin and a running wtbot service. |

## Relationship to wtbot

The Wikisource plugin never talks to a wiki directly. Every remote operation —
listing, reading and saving pages, rendering previews, fetching scans, running
OCR — is an HTTP call to **wtbot**, a separate Python (FastAPI) service that
lives in its own repository (`../wtbot` beside this checkout). wtbot caches wiki
content in SQLite, records saves in a local edit journal and pushes them to the
wiki only on an explicit commit. Its concepts, HTTP API and operations are
documented in that repository (`docs/concepts.md`, `docs/reference/`,
`docs/operations/`).

The Wikitext Language plugin has no dependency on wtbot.

## User guides

- [Wikitext editing](user/wikitext-editing.md) — file types, highlighting, structure view, live templates
- [Editing actions](user/editing-actions.md) — Surround With, Bold/Italic toggles
- [Connecting to wtbot](user/connecting.md) — the WTBot settings page and switching backends
- [Wikisource browser](user/browser.md) — browsing a wiki, opening pages, attached works, page quality
- [ProofreadPage editors](user/proofread-editors.md) — Page and Index editors, preview, scans, navigation
- [OCR](user/ocr.md) — the Run OCR menu, favourites and the review tool window

## Developer guides

- [Architecture](developer/architecture.md) — Gradle modules, the two plugins, dependency directions
- [Wikitext language](developer/language.md) — lexer, parser, PSI, semantic views, editing internals
- [Managed VFS](developer/vfs.md) — `wikisource-wtbot://` files, identity, saving, backend switching
- [Editors and preview](developer/editors.md) — split editors, the proofread editor, OCR client
- [Testing](developer/testing.md) — unit, data-driven lexer/parser and IDE integration tests
- [Logging](developer/logging.md) — plugin log categories and tracing a request into wtbot

Working notes (unscheduled designs and open work) are under `internal/`; see
[the folder index](README.md).
