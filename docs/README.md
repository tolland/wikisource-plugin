# Documentation index

Organised by **purpose**, not by topic:

| Folder | Holds | Read it when |
|---|---|---|
| `todo/` | actionable, unfinished work, in priority order | you are picking up the next piece |
| `design/` | future designs that remain relevant but are not scheduled | you are about to build something they touch |
| `reference/` | current architecture, operational notes, empirical findings | you need to know how the system behaves today |
| `done/` | completed implementation plans, retained for history | you are asking "why is it like this?" |

Nothing in `done/` describes work still outstanding, and nothing in
`reference/` describes work that has not shipped. If a document turns out to be
both, split it rather than filing it twice.

Architecture overview lives in the repo root (`CLAUDE.md` / `AGENTS.md`); the
backend data model and fetch/edit/commit contract live in `src-py/DESIGN.md`.

This folder is also published as a site, from `mkdocs.yml` at the repo root:

```bash
uv run --group docs mkdocs serve          # live preview on 127.0.0.1:8000
uv run --group docs mkdocs build --strict # what CI runs
```

`.github/workflows/docs.yml` builds every PR and publishes `develop` to the
`gh-pages` branch. `--strict` fails on a page that is not in `mkdocs.yml`'s
`nav`, so adding a document means adding it there too.

---

## `todo/` — actionable work, in priority order

| Doc | Surface | Status | Next action |
|---|---|---|---|
| [`upstream-sync-TODO.md`](todo/upstream-sync-TODO.md) | wtbot (sidecar) | in progress — report, links and promotion batches built | **Rollback.** Mass promotion must not ship without it (discussion §10). Then push-path safety: `baserevid` + `createonly`/`nocreate` + error-code mapping. |
| [`editing-actions-plan.md`](todo/editing-actions-plan.md) | plugin (`wikitext-ui`/`-core`) | in progress — Surround With and quote lexing shipped | **2b: toggle actions** — `WtBaseToggleStyleAction` + token-based detection + `ActionPromoter` for the Ctrl+B/Ctrl+I shortcut conflict. |
| [`api-refactoring-plan.md`](todo/api-refactoring-plan.md) | wtbot (HTTP surface) | phase 1 applied, phases 2–5 open | **`SiteCredentialOut`** — stop returning the plaintext password from `GET /sites/{pk}/credential`. Then the shared `resolve_page_leaf` dependency. |
| [`backlog.md`](todo/backlog.md) | mixed | unowned odds and ends | Nothing blocking. The one item with independent merit: key the scan bytes cache on the image rather than `{page_pk}-{width}`. |

## `design/` — relevant, not scheduled

| Doc | Surface | Status | Next action |
|---|---|---|---|
| [`upstream-sync-discussion.md`](design/upstream-sync-discussion.md) | wtbot | living rationale for the sync feature | Read before touching anything in `todo/upstream-sync-TODO.md`; it is the *why* behind every item there. |
| [`scan-image-modeling.md`](design/scan-image-modeling.md) | wtbot model + plugin | speculative; nothing implemented | Decide whether to normalise annotation coordinates to fractions — the one item worth doing on its own merits. |
| [`templatedata-future.md`](design/templatedata-future.md) | plugin + wtbot | speculative; nothing implemented | Nothing to build. Keep the editing-feature seams (pure renderers, sidecar-mediated data) compatible. |

## `reference/` — how it works now

| Doc | Surface | Status | Next action |
|---|---|---|---|
| [`cluster-topology.md`](reference/cluster-topology.md) | all services | current | What a running system is made of, in each of its three arrangements. §4 lists the port conventions the code and `AGENTS.md` currently disagree about. |
| [`api-contract-inventory.md`](reference/api-contract-inventory.md) | wtbot HTTP | current: 20 routers, 78 paths, 99 operations | Keep in step with the routers; the changes proposed on top of it are in `todo/api-refactoring-plan.md`. |
| [`preview-design.md`](reference/preview-design.md) | plugin + wtbot | live behaviour | Explains the split editor, the `action=parse` choice and the proofread page form. Consult before changing preview or the editor-by-content-model mapping. |
| [`ocr-design.md`](reference/ocr-design.md) | plugin + wtbot | live behaviour | Explains the backend contract, engine discovery and the generated favourites menu. |
| [`locator-index-design.md`](reference/locator-index-design.md) | wtbot | first cut implemented | The one inferential `<pagelist>` rule is flagged in the doc and tracked in `todo/backlog.md`. |
| [`logging.md`](reference/logging.md) | all components | live behaviour | Start here when tracing a failing request end-to-end; §0 is the port conventions. |
| [`proofread-page-sha1-discordance.md`](reference/proofread-page-sha1-discordance.md) | wtbot | empirical finding | Why cross-wiki comparison must hash served content, not `Revision.sha1`. Read before writing anything that compares revisions. |
| [`check_revisions.http`](reference/check_revisions.http) | wtbot | scratch requests | Ready-made `recentchanges` queries against en.wikisource. |

## `done/` — completed, retained for history

| Doc | Surface | Status | Next action |
|---|---|---|---|
| [`upstream-sync-built.md`](done/upstream-sync-built.md) | wtbot | shipped | None. The record of the revision store, the link model, the sync report, the proposal endpoint and promotion batches. |
| [`editing-actions-built.md`](done/editing-actions-built.md) | plugin | shipped | None. Surround With, the `WtWrapTags` catalog, and apostrophe-quote lexing. |
| [`wtbot-base-url-switching.md`](done/wtbot-base-url-switching.md) | plugin (`wikitext-vfs`) | shipped | None; its two residual items are in `todo/backlog.md`. |
</content>
