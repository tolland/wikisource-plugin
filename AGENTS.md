# AGENTS.md

## Gradle / build commands

When running Gradle in this repository, always use a workspace-local Gradle user home.

Use:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew <task>
