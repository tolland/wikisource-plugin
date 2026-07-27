# AGENTS.md

## Gradle / build commands

When running Gradle in this repository, always use a workspace-local Gradle user home.

Use:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew <task>
```

## Python conventions

We are using modern python version 3.13 and above for generics, type aliases, better f-strings, and unpacking kwargs. please use modern python.

we should favor typed classes and try to avoid dict-based data passing

## General Coding style and approach

I anticipate that the UI design and functionality will evolve over time. Therefore we should design features and API to be easy to understand.
