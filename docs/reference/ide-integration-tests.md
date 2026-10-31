# IDE integration tests

The root `integrationTest` task uses JetBrains Starter and Driver with JUnit 5
and the IDE version selected by `intellijPlatformVersion`. It is opt-in and is
not part of the normal unit-test/check cycle.

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTest
```

The default task runs only `projectProvidesEditorAndToolWindows`: one IDE
launch covering project startup, a wikitext editor, and tool-window availability.
The additional interaction scenarios are tagged `extended` and run only
through the explicit `integrationTestExtended` task:

```bash
# All optional tool-window scenarios
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended

# Just one optional scenario
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*debugRefreshShowsBackendStatus*'

# Everything
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTest integrationTestExtended
```

`integrationTest --tests ...` selects within the default smoke suite; use
`integrationTestExtended --tests ...` for an extended scenario.

A graphical desktop is required. On Linux CI, run the same command under Xvfb:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest
```

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

For observation during development, each test pauses for three seconds before
closing the IDE, even after an assertion failure. The pause lives in the shared
`withProject` helper's `finally` block in `PluginStartupTest`; remove it there
once it is no longer useful. It runs in the test process, leaving the IDE's UI
thread responsive.

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
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTest -PintellijPlatformVersion=2026.2.4
```

A version not already cached requires a download. Gradle reuses its cached IDE
for subsequent runs; Starter still creates an isolated copy for execution.

## Platform unit tests on 2026.2.4

The module `test` tasks suppress `com.intellij.modules.ultimate`. Its bundled
project startup activity (`Q.Q.Q.Q.V`) cannot be constructed by the light
platform fixture in this GA build, causing unrelated project tests to fail
before their assertions run. The unit suites use the free platform APIs and
have no dependency on that plugin. The suppression is scoped to module unit
test JVMs; development launches and the real IDE integration suite retain their
normal plugin configuration. Revisit this workaround when upgrading the IDE.

## Managed local wtbot

The optional `seededBackendIsVisibleInDebugWindow` test uses a JUnit extension
to launch wtbot directly from the local uv environment, without Docker, pytest,
or MediaWiki:

```bash
DISPLAY=:88 GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew integrationTestExtended --tests '*seededBackendIsVisibleInDebugWindow*' --no-daemon
```

Omit `DISPLAY=:88` for a desktop run. The extension is a JUnit lifecycle callback,
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
