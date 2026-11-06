# Documentation reorganisation — plan

Status: proposed. Spans three repositories: this plugin repo, `../wtbot`
(git initialised, one commit) and a future dedicated viewer repo split out of
`../wtbot/viewer`.

## Goal

Turn `docs/` from a diary of several months of experimentation into documents
that describe the system **as it is**, owned by the repo whose code they
describe, and shaped so they can be published later without restructuring.

Not in scope now: choosing or wiring a publishing tool for the plugin (a
Kotlin/JetBrains-appropriate tool comes later; this repo has no
`pyproject.toml`, so the MkDocs setup on
`origin/claude/docs-reorganize-by-purpose-8puh0i` is not brought over here).
wtbot is Python, so it takes MkDocs (Material) from that branch.

## Principles

- **Present tense, owned by one repo.** A doc describes current behaviour of
  code in its own repo. Cross-repo facts are stated once, in the repo that
  owns the contract, and linked from the other.
- **History lives in git.** `done/` is retired. Rationale that still explains
  current code is folded into the reference page for that code ("Why it is
  like this" section); the narrative of how we got there is deleted.
- **Verify before keeping.** Every class, endpoint, path, port and command a
  doc cites is checked against the code. Implemented plans become reference;
  superseded ones are deleted.
- **Publishable layout, internal notes separated.** User and developer pages
  are written for a reader who wasn't here; `todo/` and `design/` stay as
  working notes in `internal/`, outside any future site nav.
- **Agent files point, don't duplicate.** `CLAUDE.md`/`AGENTS.md` keep build
  commands and hard rules, and link to developer pages for architecture.

## Target layout

### Plugin repo (`wikisource`)

```
README.md                  landing page: the two plugins, install, build, links
docs/
  index.md                 overview; relationship to wtbot
  user/
    wikitext-editing.md    local .wt/.wiki support, highlighting, structure
    editing-actions.md     Surround With, wrap tags, (toggle actions when built)
    connecting.md          WTBot settings, switching backends, -PwtbotBaseUrl
    browser.md             Wikisource Browser, attached works, @pages
    proofread-editors.md   ProofreadPage editors, preview, scans, page nav
    ocr.md                 Run OCR menu, engine discovery (client view)
  developer/
    architecture.md        Gradle modules, two plugins, process split
    language.md            lexer/parser, frame stack, token/rule name rule
    vfs.md                 managed VFS, WtManagedAddress, identity, backend switching
    testing.md             unit, data-driven lexer/parser, IDE integration tests
    logging.md             plugin log categories, sandbox-config
  internal/
    todo/                  plugin-split remainder, editing-actions, backlog
    design/                templatedata, work-outline navigation, …
```

### wtbot repo

```
README.md                  what wtbot is, install, run, register a site, fetch/drain
CLAUDE.md / AGENTS.md      sidecar commands, conventions, ports, pragmas
mkdocs.yml                 from the docs branch, nav rewritten
docs/
  index.md
  concepts.md              fetch/edit/commit model (refreshed src/DESIGN.md)
  operations/              cluster topology, ports, docker harness, logging,
                           cache-delete, force-revision-link, transclusion CLI
  reference/               HTTP API inventory, VFS path grammar, preview render,
                           OCR backend, locator index, content models,
                           sha1 discordance, upstream sync (built)
  internal/todo/           api-refactoring, upstream-sync TODO, backlog
  internal/design/         pages-and-existence, user mapping, scan modelling,
                           work outlines (PDF/proposal part)
```

### Viewer (prepared for its own repo)

Docs that only concern the viewer move into `../wtbot/viewer/` now, so the
split is a `git subtree split` / directory move with no doc surgery:

```
viewer/README.md           purpose (debug + out-of-band approval), dev, build,
                           WTBOT_API_URL, ports, docker image
viewer/docs/               page-tree sync, sync/approval workflow pages
```

## Document disposition

| Current doc | Destination | Action |
|---|---|---|
| `todo/plugin-split-plan.md` | plugin | Module table + rationale → `developer/architecture.md`. Phase 2 is done; only phases 3–5 (process markers, RPC/split mode, verifier/CI/release) remain as a short todo. |
| `todo/managed-vfs-migration.md` | plugin | Core complete → merge into `developer/vfs.md`; residue to backlog. |
| `todo/editing-actions-plan.md` | plugin | Stays in `internal/todo/` (toggle actions not built). |
| `done/editing-actions-built.md` | plugin | → `user/editing-actions.md` + design notes in `developer/language.md`. |
| `done/wtbot-base-url-switching.md` | plugin | → `user/connecting.md` + switching section of `developer/vfs.md`. Fix stale `wikitext-vfs` names. |
| `reference/work-attachments.md` | plugin | → `user/browser.md`. |
| `reference/ide-integration-tests.md` | plugin | → `developer/testing.md`. |
| `reference/preview-design.md` | split | Editor/split-view → plugin `user/proofread-editors.md`; `/preview/render` and the `action=parse` choice → wtbot reference. |
| `reference/ocr-design.md` | split | Menu/UI → plugin `user/ocr.md`; backend contract → wtbot. |
| `reference/vfs-paths.md` | split | Path grammar/server tree → wtbot; client addressing → plugin `developer/vfs.md`. |
| `reference/logging.md` | split | Plugin log categories stay; wtbot logging + port conventions → wtbot `operations/`; viewer bits → viewer README. |
| `design/typed-semantic-views.md` | plugin | `WtSemanticViews` exists → fold into `developer/language.md`. |
| `design/templatedata-future.md` | plugin | Stays in `internal/design/`, trimmed. |
| `design/work-outlines.md` | split | VFS navigation → plugin internal design; PDF/proposal → wtbot. |
| `design/scan-annotation-normalization.md` | wtbot | `normalized_*` implemented → verify, fold into reference or delete. |
| `design/pages-and-existence.md` (602 lines) | wtbot | Split: implemented model → `concepts.md`; open steps → internal design. Heavy trim. |
| `design/proofread-page-user-mapping.md`, `scan-image-modeling.md` | wtbot | `internal/design/`. |
| `design/upstream-sync-discussion.md`, `done/upstream-sync-built.md`, `todo/upstream-sync-TODO.md` | wtbot | Merge into one reference (what is built + why) and one todo. |
| `reference/api-contract-inventory.md`, `todo/api-refactoring-plan.md` | wtbot | Reference + todo. Viewer-only endpoints flagged as the viewer's contract. |
| `reference/locator-index-design.md`, `proofread-page-sha1-discordance.md`, `transclusion-generation.md`, `cache-delete.md`, `force-revision-link.md`, `check_revisions.http` | wtbot | Move; fix `src-py/` paths. |
| `reference/page-tree-sync.md` | viewer | → `viewer/docs/`. |
| `reference/cluster-topology.md` (docs branch) | wtbot | `operations/`; reconcile the port disagreements it lists. |
| `todo/backlog.md` | split | Split items by repo. |
| `training_tex_ocr/` | wtbot (or py-ocrapi) | Move to `internal/design/`. |
| `images/*.png` | — | Unreferenced; delete unless reused in user pages. |
| `wtbot/src/DESIGN.md` | wtbot | Says "draft / proposal"; refresh into `docs/concepts.md`. |
| `wtbot/src/wtbot/maintenance/README.md` | wtbot | Keep beside code; link from operations. |

## Viewer split preparation

Coupling found today, to be documented (and where cheap, loosened) so the
viewer can leave:

- **Backend-for-frontend router** — `wtbot/api/viewer.py` (`/viewer` prefix)
  plus other routers the viewer reads. Document these as the viewer's
  contract in the wtbot API reference; they stay in wtbot.
- **Build context** — `docker/viewer/Dockerfile` copies `viewer/` from the
  wtbot build context, and `compose.wtbot.yml` defines the `viewer` service
  (`api` profile, `network_mode: host`). On split: the Dockerfile moves with
  the viewer; wtbot compose references a published image or a sibling path.
- **API address** — `vite.config.ts` proxies `/api` to `WTBOT_API_URL`
  (default `http://127.0.100.1:18564`). Document as the only configuration
  point.
- **Ports disagree** — vite dev 18563 vs `AGENTS.md` 18573 (compose) / 18583
  (tests); likewise wtbot 18564 / 18574 / 18584. Write one table in wtbot
  `operations/ports.md`, make the viewer README link to it.
- **CI** — check wtbot `.github/workflows` for viewer steps; give the viewer
  its own `npm run check` workflow ready to move.

## Root files

- **Plugin `CLAUDE.md`**: drop the sidecar sections (SQLite pragmas,
  `src/wtbot` tour, CLI, docker harness, viewer). Keep a short "Backend"
  paragraph: wtbot lives in `../wtbot`, the plugin talks HTTP only, how to
  point `runIde` at it. Link to `docs/developer/*` instead of restating
  architecture.
- **Plugin `AGENTS.md`**: keep Gradle and IDE-integration-test rules and
  the 18590–18599 range; move docker/pytest ports and namespace-ID notes to
  wtbot.
- **Plugin `README.md`**: replace the Alembic note with a landing page.
- **wtbot**: create `README.md`, `CLAUDE.md`, `AGENTS.md` from the moved
  sections; add `mkdocs.yml` and `docs.yml` workflow from the docs branch with
  a rewritten nav and the `docs` dependency group in its `pyproject.toml`.

## Sequence

1. **Mechanical move** (no content edits): wtbot-owned docs → `../wtbot/docs/`,
   viewer-owned → `../wtbot/viewer/docs/`, plugin docs into the new folders.
   One commit per repo, so later diffs show content changes only.
2. **Verify and condense, per doc**: check cited code; delete implemented /
   superseded / narrative; rewrite in present tense; merge the upstream-sync
   trio and the split plan. Can run as parallel agents (plugin, wtbot, viewer)
   with a review pass.
3. **Write new pages**: plugin `index.md`, `user/*`, `developer/architecture.md`;
   wtbot `README.md`, `concepts.md`, `operations/ports.md`; viewer `README.md`.
4. **Root files** for both repos as above.
5. **wtbot MkDocs**: bring over config, `mkdocs build --strict` clean.
6. **Sweep**: grep all repos for `src-py`, `wikitext-vfs`, `wikitext-ui`,
   `docs/reference/…` paths that crossed repos, and stale ports; fix or link.

## Done when

- No doc in either repo cites a path, class or endpoint that does not exist.
- Every remaining `todo/` item is unbuilt; nothing in `reference/` is
  unbuilt.
- The plugin repo contains no wtbot or viewer operational docs; wtbot's
  `mkdocs build --strict` passes.
- `wtbot/viewer/` can be split into its own repo by a directory move with
  only compose/Dockerfile path changes.
