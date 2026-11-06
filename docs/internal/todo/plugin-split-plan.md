# Plugin split — remaining work

The two distributions exist and build independently; see
[Architecture](../../developer/architecture.md) for the current layout. What is
left is the process split (frontend/backend for remote development), a real
RPC layer, and release readiness.

## 1. Process modules

Today no content module declares `intellij.platform.frontend` or
`intellij.platform.backend`, so everything loads in one process.

- [ ] Decide the Language side's process layout. It is one
      `wikitext-language-ui` module mixing PSI-based work (annotators,
      structure view model, surround/toggle edit logic) with UI (settings
      page, actions). Either split it into backend/frontend modules or keep it
      shared and record why each extension is process-neutral. Audit against
      the pinned SDK/DevKit rather than assuming (`DocumentListener`, syntax
      highlighters and live templates are listed as shared in the SDK docs).
- [ ] Add the process markers to the Wikisource backend and frontend
      descriptors and the matching Gradle `bundledModule` dependencies. The
      plugin.xml already has `required-if-available` on both; also drop the
      redundant `loading="required"` where the conditional form applies.
- [ ] Remove the frontend → backend dependency (Gradle `implementation` and
      descriptor `<module name="wikisource.wikisource-remote-backend"/>`).
      Frontend code currently calls `WtVfsService`, `WtWikiFiles`,
      `WtbotAppSettings`, `OcrFavoritesProjectSettings` and `OcrCatalogService`
      directly; each needs a shared contract or an RPC call.
- [ ] Move UI out of the backend module: `WtbotConfigurable`,
      `OcrFavoritesConfigurable`, `OcrFavoriteDialog` and the
      `Messages` dialog in `WtBackendSwitcher.confirmPendingEdits()`. Settings
      state stays backend-side; the frontend edits it through the contract.
- [ ] Move the plugin-level `<depends>com.intellij.modules.jcef</depends>` into
      the frontend module only, and check behaviour on clients without JCEF.
- [ ] Audit `WtFacetType` / `WtFacet` (an SDK-sample "SDK Facet" with a
      "Path To SDK" field, still registered in `wikitext-core`): delete it, or
      give it a real purpose (e.g. the site a local `.wt` file belongs to; see
      `internal/design/templatedata-future.md`).
- [ ] `ProofreadInlayProvider` is unregistered and still reads strings from the
      frontend's `MyMessageBundle`; give it a home and bundle before enabling.

## 2. RPC and remote file opening

`WtRemotePageRpcService` (shared), `WtRemotePageRpcServiceImpl` (backend, an
application service) and `WtRemotePageRpcClient` (frontend, a service lookup)
are an unused prototype, not platform RPC.

- [ ] Replace the prototype with platform RPC (`@Rpc` interfaces in the shared
      module). Start with one vertical slice: browse the tree and open a remote
      file. Check how the platform synchronises VFS and editors in split mode
      before designing any document transport; do not assume the custom
      filesystem exists in the client process.
- [ ] Then migrate preview rendering, reference images, annotations and text
      ranges, page navigation and OCR. Requests carry page identifiers and
      revision/version tokens, support cancellation, and return typed
      snapshots so stale responses cannot overwrite newer edits.
- [ ] wtbot addresses must resolve on the IDE backend host; a frontend
      `localhost` must not silently select a different service.
- [ ] Exercise browse/open/save, wtbot failures, cancellation and refresh in
      split mode.

## 3. Verification, CI and release

CI (`.github/workflows/build.yml`) already builds both archives, runs `check`
and runs `verifyPlugin` for both.

- [ ] Make the Wikisource verifier fail on problems: its `failureLevel` is
      empty, while the Language plugin fails on compatibility, internal-API
      and override-only usages. Known internal-API users:
      `WtManagedSaveRecovery` (`PersistentFSImpl`, `FileDocumentManagerImpl`),
      `findFileByPathIfCached`, the `virtualFileSystem` extension.
- [ ] Verify the two archives contain no duplicate classes or extension
      registrations.
- [ ] Smoke-test the Language plugin alone: local `.wt`/`.prp` editing with no
      network activity, no Wikisource tool windows or settings, `.prp` falling
      back to the text editor. Then both together, disabling/uninstalling
      Wikisource, and settings persistence.
- [ ] Test upgrade from the former single-plugin install (ID
      `org.limepepper.lang.wikitext`, which the Language plugin kept).
- [ ] Define the compatible Language-version range for Wikisource, publish
      Language first, and document installation.
- [ ] Replace placeholder metadata in both `plugin.xml` files (vendor names
      and `https://www.mycompany.com`).

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew \
    :wikitext:wikitext-language-plugin:buildPlugin :wikisource:wikisource-remote-plugin:buildPlugin \
    :wikitext:wikitext-language-plugin:verifyPlugin :wikisource:wikisource-remote-plugin:verifyPlugin
```

## References

- [Frontend, Backend, and Shared APIs](https://plugins.jetbrains.com/docs/intellij/frontend-backend-shared-apis.html)
- [Modular Plugins](https://plugins.jetbrains.com/docs/intellij/modular-plugins.html)
- [RPC](https://plugins.jetbrains.com/docs/intellij/remote-procedure-calls.html)
- [Configuring Split Mode](https://plugins.jetbrains.com/docs/intellij/configuring-split-mode.html)
- [Plugin Management in Split Mode](https://plugins.jetbrains.com/docs/intellij/plugin-management-in-split-mode.html)
