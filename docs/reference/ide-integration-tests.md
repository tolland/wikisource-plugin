# IDE integration tests

The root `integrationTest` task uses JetBrains Starter and Driver with JUnit 5
and the IDE version selected by `intellijPlatformVersion`. It is opt-in and is
not part of the normal unit-test/check cycle.

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest
```

The default task runs only `projectProvidesEditorAndToolWindows`: one IDE
launch covering project startup, a wikitext editor, and tool-window availability.
The additional interaction scenarios are tagged `extended` and run only
through the explicit `integrationTestExtended` task:

```bash
# All optional tool-window scenarios
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended

# Just one optional scenario
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*debugRefreshShowsBackendStatus*'

# Everything
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest integrationTestExtended
```

`integrationTest --tests ...` selects within the default smoke suite; use
`integrationTestExtended --tests ...` for an extended scenario.

A graphical display is required. Agent runs on Linux use Xvfb, including on a
developer workstation, to avoid opening windows or taking focus on the user's
desktop:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest
```

Omit `xvfb-run -a` only for an explicitly requested visible desktop run.

To watch a run on the existing display `:88` (the user's current preference):

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededManagedEditorSavesAndReopens*' --no-daemon
```

This uses the existing display rather than creating or stopping an X server.

Bounded project attachment has two seeded scenarios:

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededWork*' --no-daemon
```

`seededWorkAttachmentPersistsAndDetaches` launches the IDE three times against
one temporary project: attach an Index, reopen the project and detach while its
editor has unsaved text, then reopen again to verify persisted detachment.
It checks canonical Page/Index editor identity, duplicate attachment suppression,
saved membership/identity metadata and independent saving after detach.
`seededWorkMembershipRefreshAndRecovery` removes one seeded Page through the
test-owned backend API, refreshes membership, stops/restarts wtbot and replaces
the database at the same address. Failure must retain the last confirmed
membership; replacement requires explicit reattachment. See
[work attachments](work-attachments.md) for the supported behavior.

Gradle may download the IDE and test framework on the first run. Starter uses
a separate copy of Gradle's resolved IDE installation rather than selecting the
latest available IDE. Allow disk space for that copy. To compile the tests
without launching an IDE:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew compileIntegrationTestKotlin
```

`PluginStartupTest` copies the bundled `projects/wikitext/sample.wiki` fixture
into a fresh JUnit temporary project and opens that project in a real IDE with
the built plugin installed. It waits for indexing, verifies the plugin is loaded,
opens the wikitext file and checks its editor text, then opens the Project and
Wikisource OCR tool windows and checks they are visible. The IDE closes before
JUnit removes the temporary project, so IDE metadata and edits never modify
the source fixture. The test trusts only its generated project through the
isolated IDE's VM options. It also seeds a test-owned Darcula theme configuration
to avoid the default Islands theme's missing editor scheme error in 2026.2.4.

IDE-process error reports become JUnit failures outside TeamCity. The test does
not require wtbot, MediaWiki, or external wiki credentials; it checks the OCR
tool window's availability without submitting OCR requests. Further editor
workflows belong under `src/integrationTest/kotlin`.

The suite also clicks between the Wikisource window's Browser and Debug tabs,
clicks Debug's Refresh button and checks the endpoint/status display, and hides
and reopens the window to check that its selected tab survives. Backend status
may be connected or offline; these tests do not require a sidecar. Each scenario
uses its own IDE context and temporary project.

There is no observation delay by default. To pause for three seconds before each
IDE closes, including after a failure, add `-PideTestPauseSeconds=3` (0–60).
The pause runs in the test process, leaving the IDE's UI thread responsive.

## Iteration speed and plugin profiles

The default `platform` profile loads Wikisource, Performance Testing (used by
Starter), essential platform plugins and their required dependencies via
`idea.load.plugins.id`. Starter's `disableUltimateModule()` selects the supported
free-feature mode. These editor/VFS scenarios do not require Ultimate features.
The earlier full startup enabled Ultimate dynamically, unloaded several bundled
plugins and restarted indexing, producing the visible plugin-loading notification.

To exercise the full bundled-plugin environment instead:

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededManagedRefreshesExternalContent*' -PideTestPluginProfile=bundled --no-daemon
```

`OncePerProcessIdeInstaller` copies the pinned IDE once per test JVM. Starter's
`ExistingIdeInstaller` otherwise deletes and recopies that distribution for every
test context. Only the distribution is shared: each scenario retains its own
project, configuration, system cache, plugin directory and seeded backend.
Nothing is cached across test JVMs, so a new invocation picks up the current IDE
distribution. Restart scenarios still close and launch two actual IDE processes,
preserving only that scenario's directories between them.

The harness prints `IDE timing` lines for preparation, launch-to-ready, scenario
execution and shutdown. Compare these and JUnit testcase durations separately
from Gradle configuration/compilation time. Normal indexing, graceful shutdown
and IDE error reporting remain enabled. Sharing a live IDE across independent
scenarios is a separate optimization that would require explicit document,
project and backend reset contracts.

Observed on 2026-10-31 with the pinned IDE on `DISPLAY=:88`:

| Seeded scenario | Earlier bundled setup | Platform profile with distribution reuse |
|---|---:|---:|
| External refresh | 60.1 s | 35.5 s |
| IDE restart (two launches) | 86.9 s | 57.5 s |

These are individual JUnit testcase durations, including backend setup and IDE
lifecycle, excluding Gradle configuration/compilation; they are one workstation
comparison, not a statistical benchmark. The startup smoke and all three lifecycle
scenarios passed with the platform profile. The measured startup loaded 12 bundled
plugins plus Wikisource, versus roughly 130 before, without dynamic plugin
reconfiguration. After the first distribution copy, preparation of subsequent
contexts took 0.3–0.4 seconds.

The Gradle preparation sandboxes live under `build/integrationTest-sandbox`
and `build/integrationTestExtended-sandbox`.
Starter manages its actual IDE configuration, logs, and artifacts under
`out/ide-tests`, independently of `.intellijPlatform/custom-sandbox` used for
development. The saved `sandbox-config` preferences and preserved development
plugins apply only to `prepareSandbox` and the two named wtbot development
launches. They are not copied into the integration sandbox.

Tests seed the IDE's wtbot endpoint with `http://127.0.0.1:18594`. The IDE suite
uses ports 18590–18599, separate from pytest's 18580–18589 range. The default
smoke test does not start a backend. Gradle reports are in `build/reports/tests/integrationTest`
and `build/reports/tests/integrationTestExtended`.

Reference: [JetBrains integration testing guide](https://plugins.jetbrains.com/docs/intellij/integration-tests-intro.html).

## IDE version policy

`gradle.properties` pins a selected GA release in `intellijPlatformVersion`
(currently `2026.2.4`, build `262.11879.100`). Compilation, development launches,
and integration tests use that same target. Starter uses the resolved local IDE
rather than looking up the latest release independently.

Adopt a new release by explicitly changing that pin. There is no automatic
patch-release tracking: a workstation IDE update does not require downloading
another sandbox IDE. Normally keep the chosen GA baseline for its release line,
and update for a new release line or a patch whose fixes we need to test.
An exact pin prevents ordinary builds from adopting later patches silently.

For a one-off check of a specific patch without changing the repository default:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest -PintellijPlatformVersion=2026.2.4
```

A version not already cached requires a download. Gradle reuses its cached IDE
for subsequent runs; Starter still creates an isolated copy for execution.

## Platform unit tests on 2026.2.4

The module `test` tasks suppress `com.intellij.modules.ultimate`. Its bundled
project startup activity (`Q.Q.Q.Q.V`) cannot be constructed by the light
platform fixture in this GA build, causing unrelated project tests to fail
before their assertions run. The unit suites use the free platform APIs and
have no dependency on that plugin. The suppression is scoped to module unit
test JVMs. Integration tests choose the platform or bundled profile described
above; development launches retain their normal plugin configuration. Revisit
this workaround when upgrading the IDE.

## Managed local wtbot

The optional `seededBackendIsVisibleInDebugWindow` test uses a JUnit extension
to launch wtbot directly from the local uv environment, without Docker, pytest,
or MediaWiki:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*seededBackendIsVisibleInDebugWindow*' --no-daemon
```

`xvfb-run -a` selects an available virtual display. The extension is a JUnit lifecycle callback,
so it also runs when the test is launched from IntelliJ (using the existing
Gradle test configuration). Only methods annotated `@WithWtbot` start a server;
other tests can continue working with an already running API.

For every managed test, `WtbotServerExtension` creates a new directory under
`build/ide-backends`, sets `PYTHONPATH`, `WTBOT_DATABASE_URL`, `WTBOT_BLOB_ROOT`,
and `WTBOT_PORT`, then launches:

```bash
PYTHONPATH="$PWD/src-py" uv run --no-sync python -m ide_test_support --data-dir /absolute/new/scenario-directory --port 18594 --scenario browser
```

This command can also be run manually. The scenario module runs Alembic via
`init_db`, seeds SQLModel/domain objects, and serves the real FastAPI app through
Uvicorn. It refuses an existing database. The `browser` scenario contains site
`ide/en`, index `Index:IDE integration.djvu`, and two proofread pages with quality
metadata. It has no upstream credentials or scan images: fetching, OCR, and
rendered previews are outside this first scenario.

The extension waits up to 60 seconds for `/health` before starting the IDE. A
port already occupied on 18594 fails the managed setup instead of attaching to
that process. On completion or assertion failure it stops its process tree;
startup failures also trigger cleanup. The database and `wtbot.log` are retained
in the per-run directory, whose path is printed in the test output. These files
are local build artifacts, not maintained database dumps. The IDE retains its
existing three-second observation pause before shutdown.

## Managed VFS migration coverage

Lifecycle scenarios:

- `seededManagedRefreshesExternalContent`: inject a same-length upstream revision
  and use the browser Refresh button to update the clean editor.
- `seededManagedRejectsReplacementDatabase`: restart against independently seeded
  databases at the same URL with identical revision, timestamp and length. Verify
  clean reload, rejected stale save, retained local text and save after explicit reload.
- `seededManagedRecoversFromRequestTimeout`: configure a one-second IDE client
  timeout, delay stat and save responses before domain execution, verify retained
  text/unsaved state and successful retry after clearing the fault.
- `seededManagedConflictPreservesUnsavedText`: keep local text in the native File
  Cache Conflict dialog, attempt Save All, verify rejection and unsaved tracking,
  explicitly reload, then verify a new edit can save.
- `seededManagedSurvivesIdeRestart`: launch the same Starter context twice, preserving
  project/configuration/system directories and the backend. Change remote content
  while the first IDE is closed, then verify updated text, file ID and editor profile.
- `seededManagedRecoversFromBackendOutage`: stop the owned HTTP server, refresh and
  attempt Save All, check local text remains unsaved, restart against the same
  database, retry saving, then verify a clean Page editor refreshes with the same ID.
- `seededLegacyUrlsRestoreAsManagedFiles`: seed persisted legacy Index/properties
  editor entries plus a duplicate canonical URL; verify two managed tabs, read-only
  properties, saving and canonical URLs on disk. The second IDE launch runs with
  wtbot stopped to exercise persistent content and editor identity before recovery.

The managed test server alone exposes `POST /__ide_test/revise` for these scenarios.
It changes the seeded remote Page revision directly; it is not registered in the
production FastAPI app. This avoids simulating external changes through the IDE's
own write path or creating a local EditJournal entry. The test client forces HTTP/1.1.

For outages, `WtbotServerExtension.stopServer()` terminates only the owned process
tree. `restartServer()` launches the test module with `--resume`, retaining that
scenario's SQLite database and blobs rather than reseeding. The address and IDE
HTTP client remain unchanged. Logs append across restarts; teardown still stops
the server after each scenario. Recovery runs in `finally` so an assertion failure
does not leave IDE shutdown attempting to save into a stopped test server.

`replaceDatabase()` creates a fresh scenario directory and UUID while retaining
the listening address. `stall()` configures only the test-owned application:
matching requests wait and return 504 without reaching the domain handler. The
client times out first. This deterministic test checks failure before execution;
real timeouts after writes may have an ambiguous outcome and need reconciliation.
These controls are absent from the production app.

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededManagedRejectsReplacementDatabase*' --tests '*seededManagedRecoversFromRequestTimeout*' --no-daemon
```

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededManagedRecoversFromBackendOutage*' --tests '*seededLegacyUrlsRestoreAsManagedFiles*' --no-daemon
```

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededManagedRefreshesExternalContent*' --tests '*seededManagedConflictPreservesUnsavedText*' --tests '*seededManagedSurvivesIdeRestart*' --no-daemon
```

If Kotlin compilation exhausts its daemon heap, the validated build-time workaround
is `--max-workers=2 -Pkotlin.compiler.execution.strategy=in-process -Dorg.gradle.jvmargs=-Xmx3g`.
These flags affect that invocation, not IDE settings.

The pinned IDE has also logged a startup `ConcurrentModificationException` in
`SchemeManagerImpl.findSchemeByName` while the Project tree resolves editor
colours. The fixture now seeds its own product workspace with Project hidden
before opening the project; hiding it after startup was too late. IDE error
reporting remains enabled. Revalidate this fixture workaround on IDE upgrades.

`seededManagedEditorSavesAndReopens` opens an Index and a Page through the browser,
types into the editor (inside the Page's guarded body), invokes native Save All,
and independently checks content and local dirty state using an HTTP client in
the test process. Closing and reopening each file must retain its text and managed
ID. The fixture remains local; no upstream wiki commit is performed.

The test-owned IDE settings also seed a supported IntelliJ profiler configuration
and record the known configuration-type IDs so unavailable defaults are not recreated.
Fresh 2026.2.4 runs were logging errors during Save All for unavailable Windows and
DTrace profiler configurations on Linux. Seeding supported settings avoids those
unrelated errors without disabling IDE error reporting. Revisit this fixture
workaround when changing the pinned IDE version.

Use this suite for the completion checks in
[Managed Wikisource VFS migration](../todo/managed-vfs-migration.md). The existing
seeded Debug-window test proves connection and fixture visibility; it does not
yet prove managed-file lookup, editor saving, refresh or native replacement.

`seededManagedFilesHavePersistentIds` checks the registered managed filesystem
against Index text, Page text and properties in the seeded API. It verifies
distinct positive IDs, repeated lookup, reverse lookup through `ManagingFS` and
permissions. It does not yet cover browser entry points or editor/save parity.
Run it with:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*seededManagedFilesHavePersistentIds*'
```

`seededBrowserOpensManagedFilesAndNavigatesPages` drives the accessible
`Wikisource Browser` tree and editor toolbar. It opens Index text and read-only
properties, opens a Page, navigates next/previous, reopens via the browser to
check tab reuse, and changes page quality to verify the managed Document reloads.
It checks managed URLs/IDs, content and the Index editor profile. The Project
pane is hidden in this scenario to leave space for toolbar mouse clicks on the
small virtual display; no desktop interaction is required.

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*seededBrowserOpensManagedFilesAndNavigatesPages*'
```

The seed has no upstream credentials or scan images. Preview/image requests may
show their normal unavailable-service state; this scenario does not validate
successful rendering, scan fetching or OCR.

Add focused `@WithWtbot` scenarios as each milestone is implemented. Exercise
user-visible actions through Driver, and verify saved content independently
against the test-owned backend. Use IDE-process assertions where file identity,
Document state or PSI cannot be established from the UI alone. Extend the typed
seed scenarios when more resource kinds or a second work are needed; do not use
a developer database or the hard-coded Stevenson page as the fixture.

Keep unit/API tests for contract details and error cases. The real IDE scenarios
cover plugin registration and the complete user workflow; notebooks remain
optional diagnostics rather than required manual acceptance steps. Restart tests
must deliberately retain the scenario's IDE caches and backend database across
the restart, while remaining isolated from other tests.
