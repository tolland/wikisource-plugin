# Logging and tracing

How each component of the project logs, how to turn the knobs on, how to trace
a request end-to-end, and the dev-port conventions that keep the various ways
of running the stack from clashing.

The design goal, after the 2026-08 consolidation: **an endpoint that is
reachable but fails to handle a request must explain itself in both logs at
default settings** — one line with the real cause in uvicorn stdout, one line
(no stack trace) in the plugin's `idea.log`, joinable via a shared request id.

Components:

| Component | Log destination | Framework |
|-----------|-----------------|-----------|
| wtbot sidecar (`src-py/wtbot`) | uvicorn stdout | Python `logging` + a custom `TRACE` level |
| IntelliJ plugin (`wikitext-*` modules) | sandbox `idea.log` | IntelliJ diagnostic `Logger` |
| Viewer (`viewer/`) | browser devtools console | none (ad-hoc) |

---

## 0. Port conventions

Several deployments of the stack coexist; each gets its own port range so
nothing collides with anything else (or with common defaults like 8000/5173):

| Range | Deployment |
|-------|-----------|
| **1856x** | services run on the dev machine alongside IntelliJ (see below) |
| **1857x** | the persistent seeded docker cluster (wtbot itself on 18574) |
| **1858x** | docker clusters spun up by pytest (e.g. 18581 upstream / 18582 local wiki pair, `src-py/tests/conftest.py`) |

Within 1856x:

```
18561  (reserved) local mediawiki wikisource instance
18562  (reserved) alternate instance for sync testing
18563  Svelte viewer app                (vite.config.ts)
18564  wtbot FastAPI service            (plugin default; CLAUDE.md run command)
18565  (reserved) wikimedia-ocr instance
18566+ (reserved)
```

Only the locally-run pieces bind these ports — in the "production-ish" layout
the wikis and OCR are remote hosts (`https://wikisource-debian-13.lan`,
`https://en.wikisource.org`, `https://ocr.wikisource-debian-13.lan`) and only
wtbot (18564) and optionally the viewer (18563) run on the dev machine.

Where the defaults live: plugin → `WtbotAppSettings.DEFAULT_BASE_URL`
(18564; changeable at runtime in Settings → Tools → WTBot, or per launch via
`./gradlew runIde -PwtbotBaseUrl=…` — the docker harness on 18574 is the usual
alternative); CLI → `wtbot/cli/deps.py` `DEFAULT_BASE_URL` or the
`WTBOT_API_URL` env var; viewer → `viewer/vite.config.ts` (`server.port`
18563, `/api` proxy → `WTBOT_API_URL` or 18564). Start the sidecar with:

```bash
uv run fastapi dev src-py/wtbot/main.py --port 18564
```

---

## 1. Sidecar (wtbot)

### 1.1 Configuration entry point

All sidecar logging is configured in one place,
`src-py/wtbot/logging_config.py`. A frozen `LoggingConfig` dataclass is built
from the environment (with `.env` in the working directory loaded first, via
`python-dotenv`) **at module import time** and applied by
`configure_logging()`, which `create_app()` calls on startup. The knobs are
read once per process — restart `fastapi dev` / uvicorn after changing `.env`.
`.env.example` at the repo root documents every knob:

| Variable | Effect | Default |
|----------|--------|---------|
| `WTBOT_LOG_LEVEL` | Root logger level, by name (`DEBUG`, `TRACE`, …) or number | `INFO` |
| `WTBOT_SQLALCHEMY_ECHO` | `true` → SQL statements at INFO; `debug` → statements + result rows | off |
| `WTBOT_TRACE_DEBUG_ROUTE_TAGS` | Comma-separated router tags to trace request/response bodies for, e.g. `vfs,preview` | none |
| `WTBOT_TRACE_ALL_DEBUG_ROUTES` | `true` → body tracing for every router | `false` |
| `WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES` | Truncation limit for logged bodies; `0` = unlimited | `131072` |

### 1.2 The TRACE level

`src-py/wtbot/log_levels.py` registers a custom `TRACE` level (numeric 5,
below `DEBUG`) and adds `logger.trace(...)`. It exists so request/response
*body* dumps can be switched on independently of — and below — ordinary
`DEBUG` chatter.

### 1.3 Error responses are always logged (`wtbot.api.errors`)

FastAPI treats `HTTPException` as a handled error and renders it silently; by
default the only server-side evidence of a 502 was uvicorn's access line. The
handlers in `src-py/wtbot/api/errors.py` (registered in `create_app()`) close
that gap: **every error response is logged at default settings**, 4xx at
WARNING and 5xx at ERROR, unexpected exceptions at ERROR with traceback:

```
2026-08-07 12:00:01 ERROR [wtbot.api.errors] GET /reference-image?path=… -> 502 [scan-image-fetch-failed] request_id=3f9c21aa: scan image fetch failed: Invalid URL '/images/thumb/…': No scheme supplied. …
```

The response body is a defined error object:

```json
{"detail": "scan image fetch failed: …", "code": "scan-image-fetch-failed", "request_id": "3f9c21aa"}
```

- `detail` — human-readable cause (unchanged from FastAPI convention)
- `code` — stable kebab-case failure kind; raise `ApiError(status, detail,
  code)` instead of a bare `HTTPException` to set it (plain `HTTPException`
  gets `http-error`, unhandled exceptions `internal-error`, request
  validation failures log as `validation-error` but keep FastAPI's 422 body)
- `request_id` — echo of the client's `X-Request-Id` header (the plugin sends
  one per request), for joining plugin and sidecar log lines

Codes in use today: `scan-image-fetch-failed`, `missing-target`
(reference_image); `wiki-parse-failed`, `no-site-configured` (preview);
`path-not-a-page`, `site-not-found` (targets); `not-found`,
`not-a-directory`, `not-a-file`, `blobs-not-implemented` (vfs).

### 1.4 Request/response body tracing: `DebugLoggingRoute`

`src-py/wtbot/api/debug_logging_route.py` defines a custom FastAPI `APIRoute`
that logs request and response bodies at `TRACE`, switched per router tag
(logger `wtbot.api.debug_logging_route.<tag>`; see
`WTBOT_TRACE_DEBUG_ROUTE_TAGS`). **Every router opts in** — the full tag list
is `KNOWN_DEBUG_ROUTE_TAGS` in `logging_config.py` (`vfs`, `preview`,
`reference-image`, `page-annotations`, `ocr`, `model.py`, `commits`,
`edit-journal`, `file-blobs`, `links`, `namespaces`, `page-meta`, `page-nav`,
`pages`, `sites`, `viewer`, `health`).

Bodies are pretty-printed when JSON, decoded when text, summarized
(`<image/jpeg; 52341 bytes; body not logged>`) when binary, and truncated at
the configured limit. Error rounds trace their `detail` line before the
exception propagates to the §1.3 handler; streaming responses log
`<streaming or unavailable>`.

### 1.5 Module loggers and level policy

Best-effort code paths log on their own module logger (`wtbot.api.preview`,
`wtbot.api.reference_image`, `wtbot.wiki.client`), so each can be enabled
individually. The line between levels:

| Level | Sidecar | Plugin |
|-------|---------|--------|
| TRACE | request/response bodies | high-volume per-keystroke detail |
| DEBUG | best-effort noise (cache warming, enrichment lookups) | per-request flow |
| INFO | lifecycle (startup, migrations), access log | user-visible actions |
| WARNING | degraded results served (placeholder instead of scan), 4xx | expected sidecar errors (one line, no stack) |
| ERROR | 5xx, unexpected exceptions (with stack) | unexpected exceptions (with stack) |

Notably, `GET /reference-image` serving its placeholder instead of a real
scan logs at WARNING (`wtbot.api.reference_image`): the request *succeeded*,
so the §1.3 error handlers never see it, and that line is the only
server-side account of why the pane is blank.

### 1.6 SQL and pywikibot

- **SQLAlchemy**: `WTBOT_SQLALCHEMY_ECHO` (§1.1) sets the
  `sqlalchemy.engine` logger level and the engine's `echo` flag.
- **pywikibot**: configured programmatically in `wtbot/wiki/config.py`, no
  logging knobs set. pywikibot and `requests`/`urllib3` use standard
  `logging` namespaces (`pywiki`, `urllib3`), so `WTBOT_LOG_LEVEL=DEBUG`
  surfaces wire-level detail. Retries are fail-fast (`max_retries` from
  `WikiSettings`), so a wiki-side failure surfaces quickly instead of hiding
  behind backoff.

---

## 2. IntelliJ plugin

### 2.1 Where the log is

The sandbox IDE (`runIde`) writes IntelliJ's standard `idea.log` under the
sandbox directory, e.g. `build/idea-sandbox/<ide-version>/log/idea.log`; in
the sandbox, **Help → Show Log in Files**.

### 2.2 Loggers and categories

One diagnostic `Logger` per class under `org.limepepper.lang.wikitext.…`
(`ReferenceImagePane`, `WtPageNavToolbar`, `WtRenderPreviewPane`,
`WikisourceTreeStructure`, the sync classes, …). `warn`/`error` always reach
`idea.log`; `debug`/`trace` need the category enabled. The sandbox enables
`org.limepepper.lang.wikitext` at DEBUG out of the box via
`sandbox-config/log-categories.xml` (copied into the sandbox on every
`prepareSandbox`), so `runIde` sessions capture plugin DEBUG without
clicking through **Help → Diagnostic Tools → Debug Log Settings**. For a
production install, enable it there (`#org.limepepper.lang.wikitext`, or
`…:trace` for TRACE).

### 2.3 How sidecar errors surface in the plugin

All sidecar traffic goes through `HttpVfsBackend`
(`wikitext-vfs/.../backend/HttpVfsBackend.kt`) — including scan-image bytes
(`VfsBackend.fetchReferenceImage`), which used to be fetched around the backend
with `ImageIO.read(URL)` and therefore lost the error body. Any non-2xx
response raises `VfsBackendException` with:

- `statusCode` — the HTTP status (null for transport failures / sidecar down)
- `detail` / `errorCode` — parsed from the sidecar's error object (§1.3)
- `requestId` — the `X-Request-Id` the backend generated and sent, matching
  the sidecar's `request_id` echo and log line
- `message` — `HTTP 502 from <uri>: <detail>` (falls back to the raw body
  when it isn't the error object, e.g. a proxy's HTML page)

Call sites treat a `VfsBackendException` with a status code as an *expected*
failure: one `LOG.warn` line carrying the server's own explanation, no stack
trace (see `ReferenceImagePane.ensureLoaded`). Stack traces are reserved for
genuinely unexpected exceptions.

---

## 3. Viewer (SvelteKit debug UI)

No logging framework; failures surface in the browser devtools console and
the `npm run dev` terminal (port 18563, `/api` proxied to wtbot on 18564).
The viewer is itself a debugging surface — the sidecar-side tracing in §1.4
is usually the more useful window.

---

## 4. Cookbook: tracing a request end-to-end

Scenario: an editor pane shows "Could not load the reference image", or any
sidecar-backed feature degrades.

1. **Read the two default-settings lines first.** The plugin logs
   `reference image load failed for <path>: HTTP 502 from <url>: <detail>`
   in `idea.log`; the sidecar logs the matching
   `GET <target> -> 502 [<code>] request_id=<id>: <detail>` line in uvicorn
   stdout. The shared request id confirms they are the same request; the
   detail usually names the real cause outright.

2. **Reproduce outside the IDE** when needed — error bodies are
   self-describing:

   ```bash
   curl -sS 'http://127.0.100.1:18564/reference-image?path=…' | head -c 2000
   ```

3. **Turn up sidecar visibility** (`.env`, then restart — see `.env.example`):

   ```dotenv
   WTBOT_LOG_LEVEL=DEBUG                       # best-effort paths, urllib3/pywiki wire logs
   WTBOT_TRACE_DEBUG_ROUTE_TAGS=vfs,preview    # request/response bodies for those routers
   WTBOT_SQLALCHEMY_ECHO=true                  # if the suspect is cached DB state
   ```

4. **Plugin DEBUG** is already on in the sandbox (§2.2); watch the sandbox
   `idea.log`.

5. **Check the data, not just the code.** Many "endpoint fails to handle"
   errors are bad cached rows (e.g. a scheme-less `thumb_url` in `PageMeta`
   — the original `scan-image-fetch-failed` case). The viewer
   (`cd viewer && npm run dev`) or `sqlite3 database.db` shows the row the
   endpoint resolved.

---

## 5. Remaining gaps / future work

- uvicorn's access log and the `wtbot.api.errors` lines are separate loggers
  with separate formats; a single access-log middleware could unify them and
  stamp the request id on successful requests too.
- The reserved 1856x ports (local mediawiki pair, OCR) are unassigned until
  those services actually move into the dev-machine layout.
