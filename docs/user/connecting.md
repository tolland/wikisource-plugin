# Connecting to wtbot

The Wikisource plugin reaches every wiki through one wtbot service over HTTP.
Running and configuring wtbot itself (registering sites, credentials, fetching
pages) is described in the wtbot repository (`../wtbot`, `README.md` and
`docs/operations/`).

## The WTBot settings page

**Settings → Tools → WTBot (VFS backend)** has two fields:

| Field | Default | Notes |
|---|---|---|
| Base URL | `http://127.0.0.1:18564` | An absolute `http`/`https` URL with a host. A trailing slash is removed; a path prefix (reverse proxy) is allowed; query strings and fragments are rejected. |
| Timeout (s) | `10` | Per-request timeout, 1–600 seconds. |

**Test Connection** calls `GET /health` on the URL currently typed in the
field (not the saved one), so you can check a service before switching to it.

The setting is application-wide: one wtbot serves every open project. It is
stored in the IDE's `options/wikitext-vfs.xml`.

## Switching backends

Applying a new base URL switches the running IDE immediately; no restart is
needed.

1. If any Wikisource documents have unsaved changes, you are asked first:
   - **Save** writes them to the backend they were read from, then switches.
   - **Discard** switches and reloads those documents from the new backend.
   - **Cancel** keeps the current backend and restores the settings fields.
2. Open Wikisource editors are re-checked against the new backend. Clean
   documents reload; if the new backend is unreachable, editors keep their
   cached text until it becomes available.
3. The Wikisource browser and attached-work search scopes reload, and the OCR
   engine list is cleared so it is rediscovered from the new backend.

Rendered previews keep showing their last render until the next edit or
**Reload Preview**.

Changing only the timeout swaps the HTTP client and does nothing else.

A save is always bound to the backend database the text was read from. If you
point the IDE at a different wtbot (or a replacement database at the same
address), a document read from the old one cannot be saved into the new one;
reload it first.

## Choosing the backend at launch

The base URL and timeout can also be set when the IDE starts. These overrides
are applied on **every** launch, written into the live setting (so the settings
page shows the URL in use), and can still be changed from the settings page
afterwards.

| Mechanism | Base URL | Timeout |
|---|---|---|
| JVM system property (any IDE, e.g. in VM options) | `-Dwtbot.baseUrl=…` | `-Dwtbot.timeoutSeconds=…` |
| Environment variable | `WTBOT_BASE_URL` | `WTBOT_TIMEOUT_SECONDS` |
| Sandbox IDE from this repository | `./gradlew :runIde -PwtbotBaseUrl=…` | `-PwtbotTimeoutSeconds=…` |

An invalid override is ignored with a warning in `idea.log`.

For the development sandbox there are also two preset tasks:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew runIdeWtbotLocal   # http://127.0.100.1:18564
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew runIdeWtbotDocker  # http://localhost:18574
```

Port conventions for the different ways of running wtbot are listed in the
wtbot repository (`docs/operations/cluster-topology.md`).

## Checking the connection

The Wikisource tool window's **Debug** tab shows the base URL in use, whether
the backend answered, and the sites and namespaces it reports. **Refresh**
re-queries it.
