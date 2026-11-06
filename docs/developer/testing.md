# Testing

Always run Gradle with the repository-local user home:
`GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew …`.

## Unit tests

Each module has its tests under `src/test/` and uses the platform's light test
framework (`TestFrameworkType.Platform`).

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew test                               # all modules
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext:wikitext-core:test       # one module
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext:wikitext-core:test \
    --tests "org.limepepper.lang.wikitext.lexer.WtLexerTest"                       # one class
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew check                              # build + tests + spotless (pre-push hook)
```

| Module | Covers |
|---|---|
| `wikitext-core` | lexer, parser, semantic views, quote scanning/toggling, wrap rendering |
| `wikitext-language-ui` | sentence bands, highlighting settings, colour utilities |
| `wikisource-remote-shared` | RPC model serialization |
| `wikisource-remote-backend` | managed filesystem, paths, content models, backend switching, settings, work attachments and eligibility, `HttpVfsBackend` / `FakeVfsBackend`, JSON reader, OCR favourites |
| `wikisource-remote-frontend` | browser model, annotation geometry and models, text ranges and box links, ProofreadPage parsing, quality edits, OCR menu resolution |

Remote tests use `FakeVfsBackend` (installed with
`WtVfsService.setBackendForTesting`) or an in-process HTTP server; none needs a
running wtbot.

`./gradlew :wikisource:wikisource-remote-frontend:runAnnotationDemo` opens the
standalone `ImageAnnotationPane` harness for manual checks.

### Data-driven lexer and parser tests

Two base classes in `wikitext-core/src/test/kotlin/…/utils/` read fixtures from
`wikitext-core/src/test/testData/simple/`:

| Base class | Test method `testFooBar()` reads | Compares against |
|---|---|---|
| `WtLexerTestCase` | `fooBar.wt` | `fooBar.txt` (token dump) |
| `WtParsingTextCase` | `fooBar.wt` | `fooBar.parse.txt` (PSI tree; error elements fail the test) |

To add a case, add the `.wt` input, add a test method, run it once and review
the actual output printed in the failure before saving it as the expected
file. Set `LEXER_DEBUG=true` (system property or environment variable) for
verbose token dumps.

### Ultimate is suppressed in unit tests

The module `test` tasks set `idea.suppressed.plugins.id=com.intellij.modules.ultimate`.
On 2026.2.4 a project startup activity in that plugin cannot be constructed by
the light fixture and fails unrelated tests. The unit suites use only free
platform APIs. Revisit on IDE upgrades.

## IDE integration tests

The root `src/integrationTest` source set drives a real IDE with JetBrains
Starter and Driver (JUnit 5). Both plugin archives are built and installed.
These tests are opt-in and not part of `check`.

| Task | Runs |
|---|---|
| `integrationTest` | `projectProvidesEditorAndToolWindows` only: project startup, opening `sample.wiki`, Project and Wikisource OCR tool windows |
| `integrationTestExtended` | the tests tagged `extended` (below); supports `--tests` |

```bash
# headless (default for agents)
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*seededWork*'

# on an existing display, e.g. :88
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended \
    --tests '*seededManagedEditorSavesAndReopens*' --no-daemon

# compile only
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew compileIntegrationTestKotlin
```

A display is required. Use Xvfb unless a visible run is wanted.

Options:

| Property | Default | Effect |
|---|---|---|
| `-PideTestPluginProfile` | `platform` | `platform` loads only the two plugins plus Starter's performance plugin (`idea.load.plugins.id`) with the Ultimate module disabled; `bundled` loads the full bundled set |
| `-PideTestPauseSeconds` | `0` | pause (0–60 s) before each IDE closes, for watching |
| `-PwtbotProjectDir` | `../wtbot` | wtbot checkout used for seeded backends |
| `-PintellijPlatformVersion` | pin in `gradle.properties` | one-off run against another IDE build |

If Kotlin compilation runs out of heap:
`--max-workers=2 -Pkotlin.compiler.execution.strategy=in-process -Dorg.gradle.jvmargs=-Xmx3g`.

### Fixtures and isolation

Each test copies `src/integrationTest/resources/projects/wikitext/sample.wiki`
into a JUnit temporary project and opens it in its own Starter context
(configuration, system, plugins and logs). The fixture:

- trusts only the generated project, and pre-seeds the workspace with the
  Project tool window hidden (avoids a `SchemeManagerImpl` race on 262);
- seeds a Darcula look-and-feel (the default Islands theme references a
  missing editor scheme on 2026.2.4) and a supported profiler configuration
  (avoids Windows/DTrace profiler errors on Save All);
- turns IDE-process error reports into JUnit failures.

Revalidate these workarounds when changing the IDE pin.

`OncePerProcessIdeInstaller` copies the pinned IDE once per test JVM instead of
once per context. Starter's files are under `out/ide-tests`; Gradle's
preparation sandboxes under `build/integrationTest-sandbox` and
`build/integrationTestExtended-sandbox`; reports under
`build/reports/tests/integrationTest[Extended]`. The development sandbox
(`.intellijPlatform/custom-sandbox`, `sandbox-config/`) is not used.

### Seeded wtbot backend

Tests annotated `@WithWtbot(scenario = …)` get a private wtbot from
`WtbotServerExtension`:

- a fresh directory under `build/ide-backends/<test>-…` holding the SQLite
  database, blobs, `wtbot.log` and `failure.log` (path printed in the output);
- launched from the wtbot checkout as
  `uv run --no-sync python -m ide_test_support --data-dir <dir> --port 18594 --scenario <name>`
  with `PYTHONPATH=<wtbot>/src`;
- the IDE is pointed at `http://127.0.0.1:18594`. The IDE suite owns ports
  18590–18599; if 18594 is already taken the test fails rather than attaching
  to someone else's service;
- waits up to 60 s for `/health`; the process tree is stopped after the test.

Scenarios: `browser` (site `ide/en`, `Index:IDE integration.djvu`, two
proofread Pages with quality) and `search` (adds untouched OCR/scaffold
placeholders, a locally saved Page with no remote revision and an unrelated
title). No scenario has upstream credentials or scan images, so fetching, OCR
and successful rendering are out of scope.

The test-owned app (not the production one) adds controls used by the
extension: `revise()` (`POST /__ide_test/revise`, change a Page's remote
revision without going through the IDE's write path), `stall()` (delay
matching requests then return 504), `stopServer()` / `restartServer()`
(restart with `--resume`, keeping the database) and `replaceDatabase()` (new
database and UUID at the same address).

### Scenarios

| Test | Checks |
|---|---|
| `browserAndDebugTabsCanBeSwitched`, `debugRefreshShowsBackendStatus`, `reopeningToolWindowPreservesSelectedTab` | tool window tabs; no backend needed |
| `seededBackendIsVisibleInDebugWindow` | Debug tab shows the seeded site |
| `seededManagedFilesHavePersistentIds` | positive IDs, repeated and reverse lookup, permissions |
| `seededBrowserOpensManagedFilesAndNavigatesPages` | open Index text and properties, open a Page, previous/next, tab reuse, quality change reloads the Document |
| `seededManagedEditorSavesAndReopens` | type in the Page body, Save All, verify via HTTP, close/reopen keeps text and ID |
| `seededManagedRefreshesExternalContent` | same-length remote revision; browser Refresh updates the clean editor |
| `seededManagedSurvivesIdeRestart` | two launches; remote change while closed; same ID and editor profile |
| `seededManagedConflictPreservesUnsavedText` | keep local text in the conflict dialog, rejected save, reload, save |
| `seededManagedRecoversFromBackendOutage` | stop wtbot, refresh and save fail safely, restart, save succeeds |
| `seededManagedRejectsReplacementDatabase` | identical-looking replacement database: clean reload, stale save rejected |
| `seededManagedRecoversFromRequestTimeout` | 1 s client timeout, stalled stat/save, retry after clearing |
| `seededManagedFilesRestoreOffline` | second launch with wtbot stopped restores tabs, profile and IDs; only `wikisource-wtbot` is registered |
| `seededWorkAttachmentPersistsAndDetaches` | three launches: attach, reopen and detach with unsaved text, reopen |
| `seededWorkMembershipRefreshAndRecovery` | membership refresh after removing a Page; outage keeps the snapshot; replacement database needs reattachment |
| `attachedWorkIndexSkipsUnreviewedDefaults` (`search`) | indexing excludes untouched placeholders, the scope works in the real Find in Files dialog, a saved default joins, detach removes roots; Refresh reloads an opened result |

When adding scenarios: drive user-visible actions through Driver, verify saved
content independently over HTTP, use IDE-process assertions only for file
identity, Document state or PSI, and extend the typed seed scenarios in wtbot's
`ide_test_support` rather than using a developer database.

## IDE version policy

`gradle.properties` pins one GA release (`intellijPlatformVersion`, currently
`2026.2.4`, build 262.11879.100). Compilation, the sandbox and integration tests
all use it, and Starter uses the same resolved IDE. Change the pin deliberately;
there is no automatic patch tracking.

Reference: [JetBrains integration testing guide](https://plugins.jetbrains.com/docs/intellij/integration-tests-intro.html).
