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

- 18571 The port for the primary mediawiki instance
- 18572 For a "local" instance of mediawiki for syncing scenarios (optional to start via profile "pair")
- 18573 Svelte viewer app
- 18574 The wtbot fastapi service
- 18575 Instance of wikimedia ocr

### Ports for tests

To avoid conflicting with running docker instance, we should use the following conventional ports for test. @TODO this needs to be done, as the tests currently conflict with any docker instance running.

- 18581 Primary mediawiki instance
- 18582 Alternate instance for syncing
- 18583 Svelte viewer app
- 18584 The wtbot fastapi service
- 18585 Instance of wikimedia ocr

## mediawiki namespace IDs

Upstream en.wikisource.org uses some legacy namespace IDs. This can be seen
here: <https://en.wikisource.org/wiki/Special:NamespaceInfo> using a config 
like

```php
define( 'NS_PAGE', 104 );
define( 'NS_PAGE_TALK', 105 );

define( 'NS_INDEX', 106 );
define( 'NS_INDEX_TALK', 107 );

$wgExtraNamespaces[NS_PAGE] = 'Page';
$wgExtraNamespaces[NS_PAGE_TALK] = 'Page_talk';
$wgExtraNamespaces[NS_INDEX] = 'Index';
$wgExtraNamespaces[NS_INDEX_TALK] = 'Index_talk';

$wgProofreadPageNamespaceIds = [
'page' => NS_PAGE,
'index' => NS_INDEX,
];
```

However, due to clashes with other extensions, these namespace IDs have been moved to: 

```php
define( 'NS_PAGE', 250 );
define( 'NS_PAGE_TALK', 251 );

define( 'NS_INDEX', 252 );
define( 'NS_INDEX_TALK', 253 );

$wgExtraNamespaces[NS_PAGE] = 'Page';
$wgExtraNamespaces[NS_PAGE_TALK] = 'Page_talk';
$wgExtraNamespaces[NS_INDEX] = 'Index';
$wgExtraNamespaces[NS_INDEX_TALK] = 'Index_talk';

$wgProofreadPageNamespaceIds = [
'page' => NS_PAGE,
'index' => NS_INDEX,
];
```

The proofread-page extension when deployed from recent git checkout, we are
using 1.43 will by default, no configuration required, use the latter namespace
IDs.
