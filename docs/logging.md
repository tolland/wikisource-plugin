# Logging and tracing

How each component of the project logs today, how to turn the existing knobs
on, how to trace a request end-to-end, and a consolidation plan for the gaps —
in particular the class of failure where an endpoint is *reachable* but fails
to handle the request (an HTTP error response with a JSON `detail` body),
which today is visible in neither the sidecar's stdout nor the plugin's log
in a readable form.

Components covered:

| Component | Log destination | Framework |
|-----------|-----------------|-----------|
| wtbot sidecar (`src-py/wtbot`) | uvicorn stdout | Python `logging` + a custom `TRACE` level |
| IntelliJ plugin (`wikitext-*` modules) | sandbox `idea.log` | IntelliJ diagnostic `Logger` |
| Viewer (`viewer/`) | browser devtools console | none (ad-hoc) |

---

## 1. Sidecar (wtbot)

### 1.1 Configuration entry point

All sidecar logging is configured in one place,
`src-py/wtbot/logging_config.py`. A frozen `LoggingConfig` dataclass is built
from the environment (with `.env` in the working directory loaded first, via
`python-dotenv`) **at module import time** and applied by
`configure_logging()`, which `create_app()` calls on startup. That means the
knobs below are read once per process — restart `fastapi dev` / uvicorn after
changing `.env`.

Environment variables (all optional):

| Variable | Effect | Default |
|----------|--------|---------|
| `WTBOT_LOG_LEVEL` | Root logger level, by name (`DEBUG`, `TRACE`, …) or number | `INFO` |
| `WTBOT_SQLALCHEMY_ECHO` | `true` → SQL statements at INFO; `debug` → statements + result rows | off |
| `WTBOT_TRACE_DEBUG_ROUTE_TAGS` | Comma-separated router tags to trace request/response bodies for, e.g. `vfs,preview` | none |
| `WTBOT_TRACE_ALL_DEBUG_ROUTES` | `true` → body tracing for every router that opts in to `DebugLoggingRoute` | `false` |
| `WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES` | Truncation limit for logged bodies; `0` = unlimited | `131072` |

Example `.env` for a full-visibility debugging session:

```dotenv
WTBOT_LOG_LEVEL=DEBUG
WTBOT_SQLALCHEMY_ECHO=true
WTBOT_TRACE_ALL_DEBUG_ROUTES=true
WTBOT_DEBUG_ROUTE_BODY_LIMIT_BYTES=0
```

### 1.2 The TRACE level

`src-py/wtbot/log_levels.py` registers a custom `TRACE` level (numeric 5,
below `DEBUG`) and adds `logger.trace(...)`. It exists so that request/response
*body* dumps can be switched on independently of — and below — ordinary
`DEBUG` chatter. `install_trace_logging()` is idempotent and is called both by
`configure_logging()` and by the debug route module itself.

### 1.3 Request/response body tracing: `DebugLoggingRoute`

`src-py/wtbot/api/debug_loggig_route.py` (note the historical `loggig` typo —
the module name and the logger namespace
`wtbot.api.debug_loggig_route.<tag>` both carry it, consistently, so it
works; see the consolidation plan for the rename) defines a custom FastAPI
`APIRoute` subclass. A router opts in with
`APIRouter(..., route_class=DebugLoggingRoute)`; per-route loggers are named
after the router's first tag, so tags are the tracing switch granularity.

When the tag's logger is enabled for `TRACE`, every request logs its method,
target, and body, and every response logs its status and body. Bodies are
pretty-printed when JSON, decoded when text, summarized
(`<image/jpeg; 52341 bytes; body not logged>`) when binary, and truncated at
the configured limit.

Routers currently opted in (tag → module):

| Tag | Router |
|-----|--------|
| `vfs` | `wtbot/api/vfs.py` |
| `preview` | `wtbot/api/preview.py` |
| `page-annotations` | `wtbot/api/annotations.py` |
| `page-ocr` | `wtbot/api/ocr.py` |

Routers **not** opted in (no body tracing available today): `fetch`,
`commit`, `edit_journal`, `file_blob`, `namespace`, `page_image`
(`/pages/image`), `page_meta`, `page_nav`, `pages`, `sites`, `viewer`,
`health`, and the mounted `/ocr` app.

Two structural limitations to know about:

1. **Error responses are never traced.** `DebugLoggingRoute` wraps the route
   handler; when the handler raises `HTTPException`, the exception propagates
   *out of* the wrapper (FastAPI converts it to a JSON response further up the
   middleware stack), so the "response body" trace line never runs. Body
   tracing therefore only shows you successful responses — exactly the wrong
   way round for debugging failures.
2. **Streaming responses** log `<streaming or unavailable>` rather than a
   body.

### 1.4 What is (and isn't) logged on an error response

This is the gap behind the motivating example. A request like

```
GET /preview/page-image?path=/local/en/Index:….pdf/Pages/Page:….pdf/7
```

can fail inside `serve_scan_image()` (`wtbot/api/page_image.py`) — e.g. when
a `PageMeta` row holds a scheme-less thumb URL (`/images/thumb/...`), the
`requests.get` in `fetch_image_bytes()` raises
`Invalid URL … No scheme supplied`, and the handler wraps it:

```python
raise HTTPException(status_code=502, detail=f"scan image fetch failed: {exc}")
```

The client receives a useful JSON body:

```json
{"detail": "scan image fetch failed: Invalid URL '/images/thumb/…': No scheme supplied. …"}
```

but on the server the **only** evidence is uvicorn's access line:

```
INFO: 127.0.0.1:57682 - "GET /pages/image?path=… HTTP/1.1" 502 Bad Gateway
```

This is FastAPI's default behavior: `HTTPException` is considered a *handled*
error, so nothing logs its detail — uvicorn's `uvicorn.error` logger only
prints tracebacks for **unhandled** exceptions (500s). There is currently no
exception handler or middleware in `create_app()` (`wtbot/main.py`) that logs
4xx/5xx response bodies. Fixing this is item 1 of the consolidation plan.

### 1.5 Ad-hoc `logging.debug` on the root logger

Several best-effort code paths log failures at DEBUG **on the root logger**
(no module logger), so they appear only with `WTBOT_LOG_LEVEL=DEBUG` and
cannot be enabled per-module:

- `wtbot/api/page_image.py` — next-page cache-warming failures
- `wtbot/api/preview.py` — scan-raster fetch failures, `imageforpage` lookup
  failures (including the HTTP status + content type of a failed image GET —
  the most direct clue for the scheme-less-URL bug above)
- `wtbot/wiki/client.py` — `imageforpage`, `proofreadpagesinindex`,
  `defaultcontentforpage` query failures

These are deliberately "never fatal" paths, but at INFO they are completely
silent, which is why a degraded placeholder image or a 502 appears without
any server-side explanation.

### 1.6 SQL and pywikibot

- **SQLAlchemy**: `WTBOT_SQLALCHEMY_ECHO` (see table above) sets the
  `sqlalchemy.engine` logger level; `create_db_engine()` also receives it as
  the `echo` flag.
- **pywikibot**: configured programmatically in `wtbot/wiki/config.py`; no
  logging knobs are set there today. pywikibot and `requests`/`urllib3` use
  standard `logging` namespaces (`pywiki`, `urllib3`), so
  `WTBOT_LOG_LEVEL=DEBUG` surfaces wire-level detail from both. Retries are
  configured fail-fast (`max_retries` from `WikiSettings`), so a wiki-side
  failure surfaces quickly rather than after silent backoff.

---

## 2. IntelliJ plugin

### 2.1 Where the log is

The sandbox IDE (`runIde`) writes IntelliJ's standard `idea.log` under the
sandbox directory, e.g.
`build/idea-sandbox/<ide-version>/log/idea.log`. In the sandbox you can also
open it via **Help → Show Log in Files**.

### 2.2 Loggers and categories

The plugin uses IntelliJ's diagnostic `Logger`, one per class, e.g.:

- `org.limepepper.lang.wikitext.editor.prp.ReferenceImagePane` — scan
  load/annotation failures
- `org.limepepper.lang.wikitext.editor.prp.WtPageNavToolbar`,
  `WtAnnotationSync`, `WtBoxLinkSync`, `WtTextRangeSync`, `PrpFileEditor` —
  ProofreadPage editor chrome
- `org.limepepper.lang.wikitext.preview.WtRenderPreviewPane`,
  `…editor.prp.RenderPreviewPane` — live preview
- `org.limepepper.lang.wikitext.tool.WikisourceTreeStructure` — tool window
- `org.limepepper.lang.wikitext.vfs.settings.OcrCatalogService`

`LOG.warn(...)`/`LOG.error(...)` always reach `idea.log`; `LOG.debug`/
`LOG.trace` require the category to be enabled via **Help → Diagnostic Tools →
Debug Log Settings** (enter e.g. `#org.limepepper.lang.wikitext`, prefix with
`#` for DEBUG or append `:trace` for TRACE).

For the sandbox this is pre-configurable: `sandbox-config/log-categories.xml`
is copied into the sandbox on every `prepareSandbox`, so categories added
there are active on every `runIde` without clicking through the dialog. (It
currently enables two documentation-related categories only — adding the
`org.limepepper.lang.wikitext` tree is part of the plan below.)

### 2.3 How sidecar errors surface in the plugin

All contract traffic goes through `HttpVfsBackend`
(`wikitext-vfs/.../backend/HttpVfsBackend.kt`). Any non-2xx response raises
`VfsBackendException` whose message includes the status **and the full
response body** — i.e. the FastAPI `{"detail": ...}` JSON — plus a
`statusCode` field. Transport failures (sidecar down) surface as the same
exception type with `statusCode = null`. So for every call routed through the
backend, the server's explanation *is* available to the caller; whether it is
shown readably depends on the call site (most catch and `LOG.warn`, some show
the message in the UI).

**The known exception is image loading.** `ReferenceImagePane.loadImage()`
does not go through `HttpVfsBackend`: `pageImageUrl()` only *builds* the URL
(`GET /preview/page-image?...`), and the pane then fetches it with
`ImageIO.read(URI(url).toURL())`. When the sidecar answers 502 with a JSON
detail body, `ImageIO` throws
`IIOException: Can't get input stream from URL!` caused by
`IOException: Server returned HTTP response code: 502` — the body, the one
piece of text that explains the failure, is discarded, and `idea.log` gets a
20-frame stack trace that says nothing beyond "502". Fixing this is item 2 of
the consolidation plan. (The same applies to any other place that fetches a
sidecar URL with a raw JDK/ImageIO reader instead of the backend.)

---

## 3. Viewer (SvelteKit debug UI)

The viewer has no logging framework; failures surface in the browser devtools
console and in the terminal running `npm run dev`. Since it talks to the same
FastAPI endpoints, the sidecar-side tracing in §1.3 is usually the more
useful window — the viewer is itself a debugging surface, not a component we
instrument.

---

## 4. Cookbook: tracing a request end-to-end

Scenario: an editor pane shows "Could not load the reference image" or a
stack trace mentioning a sidecar URL.

1. **Reproduce outside the IDE first.** Copy the URL from the plugin log and
   curl it — FastAPI error bodies are self-describing:

   ```bash
   curl -sS 'http://127.0.100.1:8000/preview/page-image?path=…' | head -c 2000
   ```

   If you get JSON with a `detail` key, the endpoint is reachable but failing
   to handle the request; the detail usually names the real cause.

2. **Turn on sidecar visibility** (`.env` next to where uvicorn runs, then
   restart):

   ```dotenv
   WTBOT_LOG_LEVEL=DEBUG            # surfaces the ad-hoc logging.debug paths (§1.5)
   WTBOT_TRACE_DEBUG_ROUTE_TAGS=vfs,preview   # request/response bodies for those routers
   WTBOT_SQLALCHEMY_ECHO=true       # if the suspect is cached DB state
   ```

   Remember the §1.3 caveat: error responses are not body-traced, but the
   DEBUG lines from the failing code path (e.g. `page-image fetch failed for
   <url>: <error>`) will show.

3. **Turn on plugin visibility.** Help → Diagnostic Tools → Debug Log
   Settings → add `#org.limepepper.lang.wikitext` — or add the category to
   `sandbox-config/log-categories.xml` so every `runIde` has it. Then watch
   the sandbox `idea.log`.

4. **Check the data, not just the code.** Many "endpoint fails to handle"
   errors are bad cached rows (e.g. a scheme-less `thumb_url` in `PageMeta`).
   The viewer (`cd viewer && npm run dev`) or `sqlite3 database.db` shows the
   row the endpoint resolved.

5. **Wiki-side failures**: `WTBOT_LOG_LEVEL=DEBUG` also enables
   `urllib3`/`pywiki` wire logging for the pywikibot leg.

---

## 5. Consolidation plan

Ordered by pay-off; each step is independently landable.

### 5.1 Log error responses on the sidecar (the 502-with-silent-stdout gap)

Add an app-level exception handler for `HTTPException` (and a catch-all for
`Exception`) in `create_app()` that logs status + `detail` + method + target
before delegating to FastAPI's default JSON rendering:

- 5xx → `ERROR`, 4xx → `WARNING`, on a `wtbot.api.errors` logger.
- This makes every failed request visible in uvicorn stdout at default
  settings — no `.env` change needed — which is the single biggest
  observability win available.
- Optionally also fix `DebugLoggingRoute` to trace error bodies by catching
  `HTTPException` in the wrapper, logging, and re-raising.

### 5.2 A defined error object, and plugin-side formatting

- Sidecar: standardize error payloads as a typed model —
  `{"detail": str, "error": {"code": str, "endpoint": str, "request_id": str}}`
  — instead of bare f-string details. Existing `detail` stays for
  compatibility; `code` (e.g. `scan-image-fetch-failed`, `site-not-found`,
  `wiki-parse-failed`) lets clients branch without string matching.
- Plugin: parse the error body in `HttpVfsBackend` (it already has
  `JsonReader`) into a typed field on `VfsBackendException`
  (`detail`, `errorCode`) rather than embedding raw JSON in the message.
- Plugin: route **all** sidecar fetches through the backend. Add
  `fetchPageImage(path, width): ByteArray` to `VfsBackend` so
  `ReferenceImagePane` decodes bytes with
  `ImageIO.read(ByteArrayInputStream(...))` and a failure produces
  `LOG.warn("reference image load failed: scan image fetch failed: …")` — the
  server's own explanation, one line, no stack trace — and the same text in
  the pane's status label. Expected errors (`VfsBackendException` with a
  status code) log as `warn` *without* the throwable; only transport-level
  surprises keep the stack trace.

### 5.3 One logger namespace and level policy on the sidecar

- Replace every root-logger `logging.debug(...)` call (§1.5) with
  `logging.getLogger(__name__)` module loggers, so `wtbot.api.page_image`
  etc. can be enabled individually.
- Promote "we are about to return a degraded/error result" messages from
  DEBUG to WARNING (placeholder served because the scan fetch failed, warm
  failed repeatedly). DEBUG stays for expected best-effort noise.
- Rename `debug_loggig_route.py` → `debug_logging_route.py` and the
  `DEBUG_ROUTE_LOGGER` constant with it (one mechanical commit; the tag-based
  env knobs don't change).
- Opt the remaining routers into `DebugLoggingRoute` (or replace the
  route-class approach with one ASGI middleware that sees *all* routes,
  including the mounted `/ocr` app, and error responses — the middleware
  level is where response bodies of error JSON are actually observable).

Level policy (both sides):

| Level | Sidecar | Plugin |
|-------|---------|--------|
| TRACE | request/response bodies | high-volume per-keystroke detail |
| DEBUG | best-effort path failures, cache decisions | per-request flow |
| INFO | lifecycle (startup, migrations), access log | user-visible actions |
| WARNING | degraded results served, 4xx handled errors | expected sidecar errors (with `detail`, no stack) |
| ERROR | 5xx, unexpected exceptions (with stack) | unexpected exceptions (with stack) |

### 5.4 Cross-component request correlation

Once 5.1–5.3 are in: generate an `X-Request-Id` in `HttpVfsBackend` per
request, log it in the sidecar's error handler and access middleware, and
include it in the error object. Then a plugin log line, a uvicorn line, and a
user report all join on one id — today correlation is by timestamp and URL
guesswork.

### 5.5 Sandbox defaults

Add to `sandbox-config/log-categories.xml`:

```json
{ "category": "org.limepepper.lang.wikitext", "level": "DEBUG" }
```

so `runIde` sessions always capture plugin DEBUG without manual dialog
clicks, and document a matching `.env.example` at the repo root with the §1.1
knobs commented out.
