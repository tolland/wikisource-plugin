import os

import typer
from typer_di import TyperDI

app = TyperDI(
    no_args_is_help=False,
    name="drain",
)

"""Work the fetch queue explicitly.

Enqueueing and fetching are separate operations (see ``wtbot.api.fetch``), so
something has to say "now go and fetch". This is that something: ``fetch-page``
and ``fetch-refresh`` queue the work, ``drain`` performs it.

A drain of a freshly fanned-out book is hundreds of throttled wiki requests and
takes minutes -- that is the rate limit being respected, not a hang. The
timeout below is generous for the same reason, and ``--status`` answers "is it
worth draining" without starting one.
"""

_DEFAULT_TIMEOUT = 3600.0


@app.callback(invoke_without_command=True)
def drain(
    ctx: typer.Context,
    status_only: bool = typer.Option(
        False,
        "--status",
        help="Report queue depth and exit, without fetching anything.",
    ),
    batch: int = typer.Option(200, help="Requests claimed per pass."),
    max_passes: int = typer.Option(
        100,
        help=(
            "Safety bound on passes. Several are normal (a fan-out enqueues "
            "children mid-drain); this only stops a pathological cycle."
        ),
    ),
    timeout: float = typer.Option(
        _DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds. A large fan-out legitimately takes minutes.",
    ),
    base_url: str = typer.Option(
        lambda: os.environ.get("WTBOT_API_URL", "http://127.0.100.1:8000"),
        help="wtbot API base URL",
    ),
) -> None:
    """Fetch everything queued by ``fetch-page`` / ``fetch-refresh``."""
    if ctx.invoked_subcommand is not None:
        return

    import httpx

    root = base_url.rstrip("/")

    if status_only:
        _print_queue(httpx.get(f"{root}/fetch/queue", timeout=30.0))
        return

    before = httpx.get(f"{root}/fetch/queue", timeout=30.0)
    _print_queue(before)

    resp = httpx.post(
        f"{root}/fetch/drain",
        json={"batch": batch, "max_passes": max_passes},
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()

    typer.echo(
        f"drained {result['handled']} request(s) in {result['passes']} pass(es); "
        f"{result['remaining']} remaining"
    )
    if result["complete"]:
        return

    # Saying "done" over a queue that is not empty is the failure mode worth
    # avoiding: the caller would stop watching.
    typer.echo(f"  incomplete: stopped because {result['stop_reason']}")
    if result["stop_reason"] == "rate_limited":
        # "Run again" is the wrong advice here, and the only case where it is:
        # the wiki refused us because we are going too fast, so going again is
        # asking for the same refusal.
        wait = result.get("retry_after")
        typer.echo(
            "  the wiki rate-limited us" + (f"; it asked for {wait:g}s" if wait else "")
        )
        typer.echo(
            "  lower the request rate (WTBOT_WIKI_READ_THROTTLE) before "
            "draining again"
        )
    else:
        typer.echo("  run again to continue")


def _print_queue(resp) -> None:
    resp.raise_for_status()
    stats = resp.json()
    counts = ", ".join(f"{status}={n}" for status, n in sorted(stats["counts"].items()))
    typer.echo(f"queue: {counts or 'empty'}")
    if stats.get("oldest_pending_at"):
        typer.echo(f"  oldest pending queued at {stats['oldest_pending_at']}")
