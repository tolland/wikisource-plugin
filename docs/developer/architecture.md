# Architecture

## Two plugins

The repository builds two plugin distributions from seven Gradle projects.

| Distribution | Plugin ID | Assembly project | Depends on |
|---|---|---|---|
| Wikitext Language | `org.limepepper.lang.wikitext` | `:wikitext:wikitext-language-plugin` | `com.intellij.modules.lang` |
| Wikisource | `org.limepepper.wikisource` | `:wikisource:wikisource-remote-plugin` | `org.limepepper.lang.wikitext`, `com.intellij.modules.lang`, `com.intellij.modules.jcef` |

The Wikisource plugin requires the Language plugin and compiles against its
modules without bundling them; the Language plugin knows nothing of Wikisource.

## Modules

| Gradle path | Content module | Responsibilities |
|---|---|---|
| `:wikitext:wikitext-core` | `wikisource.wikitext-core` | File types (`WtFileType`, `PrpFileType`), lexer, parser, PSI, `<math>` → LaTeX injection, `WtSemanticViews`, pure editing helpers (`WtWrapTag`, `WtWrapRenderer`, `WtQuoteScanner`, `WtQuoteToggle`), a facet |
| `:wikitext:wikitext-language-ui` | `wikisource.wikitext-language-ui` | Syntax highlighter, sentence-band and reference annotators, Wikitext Highlighting settings, structure view, live templates, Surround With, Bold/Italic toggle actions and their `ActionPromoter`, `editing.*` registry keys |
| `:wikitext:wikitext-language-plugin` | — | Assembles the Language plugin (`plugin.xml`, content namespace `limepepper-wikitext`) |
| `:wikisource:wikisource-remote-shared` | `wikisource.wikisource-remote-shared` | Serializable contracts for the RPC prototype (`PageIdentifier`, `PageSnapshot`, `OcrRequest`, `WtRemotePageRpcService`) |
| `:wikisource:wikisource-remote-backend` | `wikisource.wikisource-remote-backend` | `wikisource-wtbot://` filesystem, `VfsBackend` / `HttpVfsBackend` / `FakeVfsBackend`, `WtVfsService`, backend switching, work attachments, WTBot and OCR-favourite settings (state and configurables), RPC prototype implementation |
| `:wikisource:wikisource-remote-frontend` | `wikisource.wikisource-remote-frontend` | Wikisource and OCR tool windows, split editors and JCEF preview, proofread page editor, scan annotation, attached-work index contributor and search scope |
| `:wikisource:wikisource-remote-plugin` | — | Assembles the Wikisource plugin (`plugin.xml`) |

Each content module's descriptor is `src/main/resources/<module name>.xml`.
The root `build.gradle.kts` pins every content-module jar to
`<root project>.<project name>` (e.g. `wikisource.wikitext-core`) so module IDs
do not depend on the parent directory a project sits in.

The root project builds no plugin of its own. It loads both plugins into the
development sandbox (`localPlugin`), owns the Starter integration tests in
`src/integrationTest`, and holds the shared SDK pin (`intellijPlatformVersion`
in `gradle.properties`). `buildSrc` provides the `class-inspector-tasks`
convention plugin applied to the module projects.

## Dependency directions

```
wikitext-core  ◀──  wikitext-language-ui
     ▲                     ▲
     │                     │
wikisource-remote-backend ◀── wikisource-remote-frontend
     │                     │
     └──▶ wikisource-remote-shared ◀──┘
```

- Language modules never depend on Wikisource modules.
- Wikisource modules reach Language modules through the plugin dependency
  plus a module dependency with `namespace="limepepper-wikitext"`; the two
  Language content modules are declared `visibility="public"` for this.
- The Wikisource frontend module currently depends on the backend module, both
  in Gradle (`implementation`) and in its descriptor. Frontend code calls
  `WtVfsService`, `WtWikiFiles` and the settings classes directly.

Content modules are loaded `required`. The Wikisource plugin.xml also carries
`required-if-available="intellij.platform.backend"` / `…frontend` on its
backend and frontend modules, but no module declares the
`intellij.platform.backend` or `intellij.platform.frontend` process marker,
so both load in the one desktop process. The plugin does not yet work in split
(remote development) mode; see `internal/todo/plugin-split-plan.md`.

## Persistent state and IDs

| State | Scope | File |
|---|---|---|
| `WtbotAppSettings` (`WtbotSettings`) | application | `wikitext-vfs.xml` |
| `OcrFavoritesAppSettings` (`WtOcrFavorites`) | application | `wikitext-ocr.xml` |
| `OcrFavoritesProjectSettings` (`WtOcrFavorites`) | project | `.idea/wikitext-ocr.xml` |
| `WtHighlightingSettings` | application | `wikitext-highlighting.xml` |
| `WtWorkAttachments` | project | `.idea/wikisource-works.xml` |

Settings page IDs keep their historical `org.limepepper.wikitext.*` prefix
(`…highlighting`, `…wtbot`, `…ocr.favorites`). Editor type IDs are
`wikitext-preview` (split editor) and `proofread-page-editor`. Action IDs are
the implementing class names.

## Why it is like this

- **Product boundary first, process boundary later.** The split separates what
  works offline (Language) from what needs wtbot, JCEF and a custom VFS
  (Wikisource). The frontend/backend module names anticipate a later process
  split, but today they are a code-ownership boundary only.
- **`.prp` belongs to Language** because it is parsed as wikitext; only its
  specialised editor is in Wikisource. Without Wikisource a `.prp` file opens
  in the normal text editor.
- **The Language plugin kept the original plugin ID.** Existing installs of
  the former single plugin therefore update to the Language plugin; Wikisource
  is a new ID that must be installed alongside it.
