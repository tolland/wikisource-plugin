# Logging

The plugins log through IntelliJ's diagnostic `Logger`, one logger per class,
under the `org.limepepper.lang.wikitext` and `org.limepepper.wikisource`
packages. Backend side (wtbot's log configuration, error codes, body tracing,
port conventions): wtbot repository (`../wtbot`), `docs/operations/logging.md`.

## Where the log is

- Development sandbox (`./gradlew :runIde`):
  `.intellijPlatform/custom-sandbox/log/idea.log`.
- Integration tests: under `out/ide-tests/` in each test context.
- Any IDE: **Help → Show Log in Files**.

## Enabling debug output

`warn` and `error` always reach `idea.log`; `debug` and `trace` need the
category enabled. In **Help → Diagnostic Tools → Debug Log Settings** add
`#org.limepepper.lang.wikitext` (or `#org.limepepper.lang.wikitext:trace`), and
likewise `#org.limepepper.wikisource`.

`sandbox-config/log-categories.xml` lists the categories intended for the
development sandbox (`org.limepepper.lang.wikitext` at DEBUG), but
`prepareSandbox` currently copies only `editor.xml`, `ide.general.xml`,
`trusted-paths.xml` and `ui.lnf.xml` from `sandbox-config/`, so set the
categories through the dialog.

## Level policy

| Level | Use |
|---|---|
| TRACE | high-volume per-keystroke detail |
| DEBUG | per-request flow |
| INFO | user-visible actions and lifecycle (e.g. backend switched) |
| WARN | expected backend failures — one line, no stack trace |
| ERROR | unexpected exceptions, with stack trace |

## Backend errors

All wtbot traffic goes through `HttpVfsBackend`, including scan bytes
(`fetchReferenceImage`). Every request carries a fresh `X-Request-Id` header
and uses HTTP/1.1. A non-2xx response raises `VfsBackendException` with:

| Field | Content |
|---|---|
| `statusCode` | HTTP status; `null` for transport failures (wtbot down) |
| `detail`, `errorCode` | parsed from wtbot's error object (`{"detail", "code", "request_id"}`) |
| `requestId` | the `X-Request-Id` sent, which wtbot echoes in its log line |
| `message` | `HTTP <status> from <uri>: <detail>`, or the raw body when it is not an error object |

Treat a `VfsBackendException` with a status code as expected: log one `warn`
line with the server's explanation (see `ReferenceImagePane`). Reserve stack
traces for unexpected exceptions.

## Tracing a failing request

1. Find the plugin's warn line in `idea.log`, e.g.
   `reference image load failed for <path>: HTTP 502 from <url>: <detail>`.
2. Find the wtbot line with the same request id in wtbot's output; it usually
   names the cause.
3. Reproduce with `curl` against the same URL — wtbot's error bodies are
   self-describing — and raise wtbot's log level as described in its logging
   guide.
4. If the code looks right, check the data: many failures are bad cached rows
   in wtbot's database.
