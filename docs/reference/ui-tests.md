# UI integration tests (Starter + Driver)

`./gradlew integrationTest` boots the real IDE with the built plugin, drives it
through the [Driver framework](https://plugins.jetbrains.com/docs/intellij/integration-tests-ui.html),
and points it at a throwaway wtbot backend in docker. Sources live in
`src/integrationTest/` (root project, its own source set; JUnit 5 only).

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTest
```

## What runs

1. `uiTestBackendUp` — `docker compose -f compose.seeded.yml -f compose.wtbot.yml
   --profile pair --profile api up -d --build --wait` under compose project
   `wtbot-ui-test`, on the **test** port block from AGENTS.md: wikis 18581/18582,
   viewer 18583, wtbot 18584. `WTBOT_RESET_DB=1`, so the sidecar starts empty
   every run; the wiki volumes are kept (they are the slow part).
2. `buildPlugin`, then the Starter tests. Starter installs the plugin zip into
   the IDE Gradle already resolved (`ExistingIdeInstaller` on
   `intellijPlatform.platformPath`) — no second IDE download — and passes
   `-Dwtbot.baseUrl` so `WtbotAppSettings` targets the test backend.
3. `uiTestBackendDown` (finalizer, also on failure) — `down`, volumes kept.

The dev stack (1857x) and the workstation sidecar (18564) are never touched.
The pytest harness (`wiki_harness`, project `wtbot-sync-pair`) also binds
18581/18582, so don't run it and `integrationTest` at the same time.

## Levels checked (`WikisourceSmokeUiTest`)

| Test | Proves |
|---|---|
| startup | IDE boots with the plugin, indexing finishes, `.wt` resolves to the `Wikitext` file type (via a `@Remote` call into the IDE, not the UI) |
| editor | `sample.wt` opens in a code editor |
| tool window | the VFS tree (`MyToolWindow`) lists a site registered on the backend — i.e. the IDE really is talking to the docker wtbot |

Every level is also a crash check: `WtIdeTestContext` rebinds Starter's
`ErrorReporter` so an exception in the IDE log attributed to this plugin
(`[Plugin: org.limepepper.lang.wikitext]` or a frame in our package) fails the
test. Platform noise (e.g. a bundled plugin's missing class, theme warnings) is
printed to the test output instead.

Under a headless X server: `xvfb-run -a ./gradlew integrationTest …`.

Backend state a test needs is created through wtbot's own HTTP API
(`WtbotTestBackend`, e.g. `POST /sites/`) in `@BeforeAll`, not baked into the
compose project.

## Knobs (Gradle properties)

| Property | Effect |
|---|---|
| `-PuiTestWtbotBaseUrl=http://…` | Skip docker; use a backend you already run |
| `-PuiTestKeepBackend` | Leave the compose project up afterwards |
| `-PuiTestComposeOverlays=compose.principles.yml` | Extra `-f` overlays (comma separated) |
| `-PuiTestComposeProject=…`, `-PuiTest{Wiki,LocalWiki,Viewer,Wtbot}Port=…` | Move the project/ports |

## Writing new tests

- `./gradlew runIdeUiTestBackend` brings the same backend up and opens a
  sandbox IDE on it. With a Driver-run IDE, the component inspector is at
  `http://localhost:63343/api/remote-driver/` — use it to find XPath
  attributes (`accessiblename`, `visible_text`, `javaclass`).
- Prefer giving plugin components an accessible name (as the VFS tree has,
  `WikisourceBrowserToolWindowTab.TREE_ACCESSIBLE_NAME`) over matching on
  class names or text.
- Scope lookups under `ideFrame { … }` and wait (`waitContainsText`,
  `waitAnyTextsContains`, `shouldBe`) rather than asserting immediately.
- IDE logs, screenshots and the test's IDE system dir land under
  `out/ide-tests/` (Starter's default); copied projects under
  `build/ui-test/projects/`.
