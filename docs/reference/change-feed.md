# Change feed (fetch observability)

Fetch results used to exist only as `FetchRequest.error_message` (one short
column) and log files. The change feed makes them first-class.

## Shape

- **`ChangeEvent` table** (`wtbot/model/change_event.py`) — append-only log.
  Topics `fetch` / `drain`; kinds `queued`, `done`, `failed`, `retried`,
  `drain_started`, `drain_finished`. Failures carry `failure_kind`,
  `http_status`, `retry_after` and a traceback tail in `detail`. Site and
  request are plain ints, not FKs, so deleting them never blocks or erases the
  record.
- **Written by the workers**, not by the server: `add_event` inside the same
  transaction as the status change (`_record_fetch_result`), `record_event` for
  drain start/finish and enqueue. A `wtbot drain` in another process therefore
  shows up with no IPC.
- **`WS /events/ws?after=<pk>&topic=`** tails the table (0.5 s poll), replaying
  from `after` (default: last 50), plus a `queue` frame whenever queue depth
  changes. `GET /events` is the same feed over REST.
- **Why a table rather than workers dialling the socket:** the socket is the
  unreliable part. A worker pushing to it loses its report exactly when the
  connection is down; a row is written regardless, and a reconnecting viewer
  asks for `after=<last pk>` and misses nothing. (The viewer also falls back to
  REST polling of the same cursor if the upgrade fails.)

## Fetch API additions

| Route | Purpose |
|---|---|
| `POST /fetch/drain/background` | drain on a server thread, return 202; one at a time |
| `GET /fetch/requests?status=` | the queue as a table |
| `POST /fetch/retry` | requeue errored requests (all, or `request_pks`) |

## Viewer

`/fetch` shows connection state, live queue counts, the event feed (expand a row
for HTTP status, retry-after, traceback), a failures tab with per-row retry,
and the queue table. State lives in `viewer/src/lib/eventFeed.svelte.ts`.
The vite dev proxy needs `ws: true` for `/api`; any production reverse proxy
must forward the `/api/events/ws` upgrade.
