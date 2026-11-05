import logging
import threading
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from wtbot.fetch.fetch_worker import ClientFactory
from wtbot.fetch.queue_runner import DEFAULT_BATCH, DEFAULT_MAX_PASSES, drain_queue

"""Draining without holding a request open.

``POST /fetch/drain`` blocks for as long as the queue takes, which is minutes
for a book and is exactly what a browser (or anything on the far side of a
flaky link) cannot be asked to wait on. This runs the same ``drain_queue`` on a
thread of the server process and returns at once; progress and the outcome
arrive on the change feed, where a dropped connection loses nothing.

At most one background drain runs at a time. A second start while one is going
is a no-op that says so -- two drainers would only split the same throttle.
"""

log = logging.getLogger(__name__)


class BackgroundDrain:
    def __init__(
        self, engine: Engine, client_factory: ClientFactory, blob_root: Path | None
    ) -> None:
        self._engine = engine
        self._client_factory = client_factory
        self._blob_root = blob_root
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(
        self, *, batch: int = DEFAULT_BATCH, max_passes: int = DEFAULT_MAX_PASSES
    ) -> bool:
        """Start a drain. False when one is already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._thread = threading.Thread(
                target=self._run,
                args=(batch, max_passes),
                name="wtbot-background-drain",
                daemon=True,
            )
            self._thread.start()
            return True

    def join(self, timeout: float | None = None) -> None:
        """Wait for the running drain; for tests."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, batch: int, max_passes: int) -> None:
        try:
            with Session(self._engine) as session:
                drain_queue(
                    session,
                    self._client_factory,
                    blob_root=self._blob_root,
                    batch=batch,
                    max_passes=max_passes,
                )
        except Exception:  # noqa: BLE001 - a thread has no caller to raise to
            log.exception("background drain crashed")
