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

The project has a uv managed virtual environment

```bash
uv run pytest
```

## General Coding style and approach

I anticipate that the UI design and functionality will evolve over time. Therefore we should design features and API to be easy to understand.


## TCP Ports for services

We want to avoid exposing services on ports that are used by common services which are likely to cause problems with conflicts.

We currently have a convention for the services in a cluster of services:

### Default ports via docker compose

For starting a cluster with single or pair of mediawiki instances

- 18581 The port for the primary mediawiki instance
- 18582 For a "local" instance of mediawiki for syncing scenarios (optional to start via profile "pair")
- 18583 The wtbot fastapi service
- 18584 Svelte viewer app
- 18585 Instance of wikimedia ocr

### Ports for tests

To avoid a running docker instance, we should use the following conventional ports for test. @TODO this needs to be done, as the tests currently conflict with any docker instance running.

- 18571 Primary mediawiki instance
- 18572 Alternate instance for syncing
- 18573 The wtbot fastapi service
- 18574 Svelte viewer app
- 18575 Instance of wikimedia ocr
