# Wikitext language and Wikisource remote editing — split plan

Status: proposed architecture; no build or runtime changes applied.

## Goal and boundaries

Produce two independently buildable plugin distributions:

1. **Wikitext Language Support**: local `.wt` / `.wiki` editing, lexer,
   parser, PSI, syntax highlighting, annotations, structure view, templates,
   and text editing actions. No WTBot, MediaWiki connection, remote VFS,
   OCR service, or JCEF requirement.
2. **Wikisource Remote Editing**: depends on Language Support and adds
   `wikisource://` files, API access, remote browsing, rendering, scan previews,
   ProofreadPage editors, annotations, and OCR review.

These product boundaries are independent of IntelliJ's frontend/backend/shared
process boundaries. Both products can contain several content modules.
“UI” is not a reliable placement rule: PSI-based inlay providers and structure
models belong on the backend even though their results appear in an editor.

## Current findings

- The root Gradle project assembles one plugin, `org.limepepper.lang.wikitext`,
  with all three content modules marked `loading="required"` and a root JCEF
  dependency.
- `wikitext-core` has parser/PSI, file types, pure text transformations, and
  facet code including a Swing editor tab. It has no process marker dependency.
- `wikitext-ui` depends on both core and VFS. Its descriptor registers local
  language features alongside remote tool windows and custom editors.
- `wikitext-vfs` contains backend VFS/API services alongside configurable
  pages and dialogs. It also needs a responsibility split.
- `ProofreadInlayProvider` uses a backend API and a message bundle owned by the
  tool-window package. Its extension registration is currently commented out;
  do not enable it as part of this migration.
- `PrpTextEditor`, preview browsers, and `WtTextRangeManager` use document
  listeners within editor functionality. Several editing and annotation
  classes also mix PSI/model work with interaction or settings concerns.
- Existing edits to the UI descriptor and message bundle must be preserved.

## Proposed module layout

Names below are proposed Gradle projects; use globally unique descriptor names.

| Distribution | Content module | Responsibilities |
| --- | --- | --- |
| Language | `wikitext-core` (shared) | Language/file types, lexer/parser/PSI, injection/manipulation, pure text transformations and semantic helpers |
| Language | `wikitext-language-backend` | Annotators, PSI structure models, inlay provider, language analysis and any backend editing operations |
| Language | `wikitext-language-frontend` | Local editor interactions, highlighting settings UI, editor listeners and frontend action handlers |
| Remote | `wikisource-remote-shared` | Typed serializable API/RPC contracts, page identifiers, remote view models; no concrete VFS or Swing classes |
| Remote | `wikisource-remote-backend` | Existing VFS, HTTP/Fake backends, API orchestration, authoritative connection settings, persistence and RPC implementations |
| Remote | `wikisource-remote-frontend` | Browser/OCR tool windows, JCEF previews, scan/annotation UI, custom editors and remote settings UI |

Basic language support remains shared to allow PSI on both sides. Audit syntax
highlighter and live-template extension placement against the pinned SDK;
keep process-neutral implementations with core where permitted. A shared
module must not become a dumping ground for mixed UI/service code.

Dependencies point from frontend/backend modules to their shared contracts.
Remote modules depend explicitly on the language plugin and the language
content modules whose classes they use. Language modules never depend on
remote modules. The frontend must not depend on the remote backend or concrete
`WtVirtualFile` implementations.

## Concrete moves and refactoring

- Split `wikitext-ui` by feature ownership first: highlighting, annotators,
  structure, templates and generic editing belong to Language; tool, preview,
  editor/prp, OCR and image annotation surfaces belong to Remote initially.
- Separate PSI analysis from frontend interactions within mixed classes rather
  than moving entire packages mechanically. For example, Surround With's PSI
  selection and its template/editor interaction need an SDK placement audit.
- Move the inlay provider's language strings into a language-owned bundle.
  Split remaining bundles and registry keys by product ownership.
- Split VFS settings into backend state/services and frontend configurables.
  Define which settings are application/project scoped and where they persist;
  frontend changes go through the service contract.
- Audit the demo facet. Remove it if unused; otherwise separate module-model
  behavior from its settings UI and retain it in the owning product.
- Keep `.prp` recognition in Language initially because it currently uses
  Wikitext PSI. The specialized editor and API behavior stay in Remote. Local
  `.prp` files must fall back to a normal text editor without Remote installed.
- Put API rendering and OCR orchestration behind backend services. Frontend
  requests use page identifiers and typed snapshots, not backend objects.
  Include cancellation, revision/version checks and errors in the contract so
  stale responses cannot overwrite newer edits or selections.
- Start with one vertical RPC slice: browse pages and open a remote file. Check
  platform VFS/editor synchronization before designing any custom document
  transport. Do not assume a custom VFS subclass exists in the client process.
- Then migrate render previews, reference images, annotations/text anchors,
  navigation and OCR. WTBot addresses resolve from the IDE backend host; a
  frontend `localhost` must not accidentally select a different service.

## Descriptors, packaging and compatibility

Create `wikitext-language-plugin` and `wikisource-remote-plugin` assembly
projects using `org.jetbrains.intellij.platform`; implementation projects use
`org.jetbrains.intellij.platform.module`. Keep the repository root as the
aggregate build and centralize SDK/Kotlin/toolchain settings.

Declare `intellij.platform.frontend` / `intellij.platform.backend` in the
respective module XML dependencies and matching Gradle bundled-module
dependencies. Shared modules have neither process marker. These dependencies,
not Gradle project names, determine the analyzer's module kind.

Use process-aware content loading, such as
`required-if-available="intellij.platform.backend"` and its frontend
counterpart, rather than unconditionally requiring modules unavailable on the
other side. Follow the pinned SDK's Plugin Model Version 2 descriptor rules;
move platform dependencies into content descriptors. Keep JCEF dependencies
only in Remote's frontend content module and verify behavior on clients without
JCEF.

Recommended ID policy: retain `org.limepepper.lang.wikitext` for the existing
Wikisource distribution, now Remote, and introduce
`org.limepepper.lang.wikitext.language` for Language. This preserves the existing
installation's remote feature set. Publish Language before a Remote release
that requires it. Preserve existing persistent-state names and action IDs
where possible. Audit any stored file-type/editor IDs before renaming them.

Remote declares a required dependency on Language. Compile against Language
without embedding its implementation JARs in Remote. Verify the two archives
contain no duplicate language classes or extension registrations. Define the
compatible Language version policy before publication.

## Delivery sequence and acceptance checks

1. **Inventory and SDK audit.** Map every extension, service, action, resource
   and test to product and process. Resolve mixed classes and record placement
   exceptions. The SDK documentation currently lists `DocumentListener` as
   shared, unlike the reported IDE warning; inspect the pinned SDK/DevKit before
   treating the interface alone as proof of frontend placement.
2. **Extract the two products.** Establish the two assembly projects and move
   local features out of the VFS-dependent module. Build both archives and
   verify Language alone handles local files without network activity or
   remote settings/tool windows. Verify both installed preserve remote editing.
   This is a desktop packaging milestone, not proof of split-mode readiness.
3. **Separate process modules.** Add markers and conditional loading; move
   mixed UI/backend implementations behind shared interfaces. Resolve DevKit
   placement warnings against the pinned SDK, including disabled prototypes.
4. **Implement RPC and remote file opening.** Validate browse/open/save in
   split mode before migrating remaining remote features. Exercise WTBot
   failures, cancellation, refresh and backend-host address resolution.
5. **Validate and release.** Run each distribution's Plugin Verifier and
   relevant lexer/PSI/editing tests. Smoke-test Language alone and both plugins
   in desktop and split mode, including uninstalling/disabling Remote, local
   `.prp` fallback, editor listener disposal, settings persistence, and upgrade
   from the previous single-plugin distribution. Add CI jobs for both archives
   and document installation/development commands.

All Gradle invocations use the repository-local user home, for example:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext-language-plugin:buildPlugin :wikisource-remote-plugin:buildPlugin
```

The project paths in this example become available after phase 2. No build or
test run is needed for this planning-only change.

## References

- [Frontend, Backend, and Shared APIs](https://plugins.jetbrains.com/docs/intellij/frontend-backend-shared-apis.html)
- [Modular Plugins](https://plugins.jetbrains.com/docs/intellij/modular-plugins.html)
- [RPC](https://plugins.jetbrains.com/docs/intellij/remote-procedure-calls.html)
- [Configuring Split Mode](https://plugins.jetbrains.com/docs/intellij/configuring-split-mode.html)
- [Plugin Management in Split Mode](https://plugins.jetbrains.com/docs/intellij/plugin-management-in-split-mode.html)

Coordinate backend API moves with `docs/todo/api-refactoring-plan.md`; this
plugin split does not require redesigning the WTBot HTTP API first.
