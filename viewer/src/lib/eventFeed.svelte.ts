import { eventsSocketUrl, listEvents } from '$lib/api';
import type { ChangeEvent, FeedFrame, QueueCounts } from '$lib/types';

export type FeedState = 'connecting' | 'live' | 'reconnecting' | 'closed';

const MAX_EVENTS = 500;
const MAX_BACKOFF_MS = 15_000;

/**
 * The server's change feed as reactive state.
 *
 * The websocket is the fast path, not the source of truth: every event is a row
 * in the server's `ChangeEvent` table and carries a `pk`. On any reconnect this
 * asks for `after=<last pk seen>`, so a dropped connection costs latency, never
 * events. If the socket cannot be opened at all (a proxy that strips upgrades,
 * say) it falls back to polling the same cursor over REST, so the page still
 * moves -- `state` says which it is.
 */
export class EventFeed {
  events: ChangeEvent[] = $state([]);
  counts: QueueCounts = $state({});
  pending = $state(0);
  state: FeedState = $state('connecting');
  polling = $state(false);
  /** Whether a drain_started has no drain_finished after it. */
  draining = $state(false);

  #socket: WebSocket | null = null;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #attempt = 0;
  #closed = false;
  #lastPk: number | undefined;
  readonly #onEvent: ((event: ChangeEvent) => void) | undefined;

  constructor(onEvent?: (event: ChangeEvent) => void) {
    this.#onEvent = onEvent;
  }

  start(): void {
    this.#closed = false;
    this.#connect();
  }

  stop(): void {
    this.#closed = true;
    clearTimeout(this.#timer);
    this.#socket?.close();
    this.#socket = null;
    this.state = 'closed';
  }

  #connect(): void {
    if (this.#closed) return;
    this.state = this.#attempt === 0 ? 'connecting' : 'reconnecting';
    let socket: WebSocket;
    try {
      socket = new WebSocket(eventsSocketUrl(this.#lastPk));
    } catch {
      this.#retryLater();
      return;
    }
    this.#socket = socket;
    socket.onopen = () => {
      this.#attempt = 0;
      this.polling = false;
      this.state = 'live';
    };
    socket.onmessage = (message) => this.#handle(JSON.parse(message.data) as FeedFrame);
    socket.onclose = () => {
      this.#socket = null;
      this.#retryLater();
    };
    socket.onerror = () => socket.close();
  }

  #retryLater(): void {
    if (this.#closed) return;
    this.#attempt += 1;
    this.state = 'reconnecting';
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** Math.min(this.#attempt, 5));
    // After a couple of failures also catch up over REST, so the page is not
    // frozen while the socket is being sorted out.
    if (this.#attempt >= 2) void this.#poll();
    this.#timer = setTimeout(() => this.#connect(), delay);
  }

  async #poll(): Promise<void> {
    try {
      const fresh = await listEvents(this.#lastPk);
      this.polling = true;
      for (const event of fresh) this.#add(event);
    } catch {
      // Still unreachable; the next reconnect attempt tries again.
    }
  }

  #handle(frame: FeedFrame): void {
    if (frame.type === 'queue') {
      this.counts = frame.counts;
      this.pending = frame.pending;
    } else {
      this.#add(frame.event);
    }
  }

  #add(event: ChangeEvent): void {
    // A replay after reconnect can overlap what the REST poll already gave us.
    if (this.#lastPk !== undefined && event.pk <= this.#lastPk) return;
    this.#lastPk = event.pk;
    if (event.kind === 'drain_started') this.draining = true;
    if (event.kind === 'drain_finished') this.draining = false;
    this.events = [...this.events, event].slice(-MAX_EVENTS);
    this.#onEvent?.(event);
  }
}
