import argparse
import signal
import sys
import threading

from wiki_harness.api import WikiApi
from wiki_harness.scenarios import (
    CANADIAN_PATENT_INDEX,
    PAGE_2,
    copy_page_to_local,
    diverge_locally,
    reconcile_to_upstream,
    seed_upstream_work,
)
from wiki_harness.stack import WikiStack, docker_available, pair_config

"""Stand the two-wiki harness up by hand and leave it running.

    PYTHONPATH=src-py/tests uv run python -m wiki_harness --scenario diverged

(the PYTHONPATH is what pytest's ``pythonpath`` ini setting does for the test
run; plain ``python`` has no equivalent.)

The pytest fixtures build these same scenarios and tear them down again, which
is right for CI and useless when what you actually want is to look at the wikis.
``--pdb`` only helps on failure; this is the same setup, held open on purpose,
against the same compose project the tests use -- so a situation reproduced here
is the one the tests assert on.

Ctrl-C exits and, by default, leaves the containers up: the expensive part is
the install and the import, and the next run reuses them.
"""

SCENARIOS = {
    "empty": "Two independent wikis, nothing in them.",
    "seeded": "The Canadian patent work imported upstream, with full history.",
    "copied": f"...plus {PAGE_2} copied to local, as a downward promotion would.",
    "diverged": "...plus a local-only edit, so the two sides disagree.",
    "reconciled": "...plus the local body put back to upstream's, ready to re-anchor.",
}


def _build(stack: WikiStack, scenario: str) -> None:
    upstream = WikiApi(stack.endpoint("upstream"))
    upstream.login()
    local = WikiApi(stack.endpoint("local"))
    local.login()

    if scenario == "empty":
        return

    print("seeding upstream (import; slow the first time)...", flush=True)
    seed_upstream_work(stack, upstream)
    if scenario == "seeded":
        return

    print(f"copying {PAGE_2} to local...", flush=True)
    copied = copy_page_to_local(upstream, local)
    print(f"  upstream revid {copied.upstream_revid}, local revid {copied.local_revid}")
    if scenario == "copied":
        return

    if scenario == "diverged":
        print(f"diverging local: revid {diverge_locally(local)}")
        return

    if scenario == "reconciled":
        diverge_locally(local)
        print(
            f"reconciling local to upstream: revid {reconcile_to_upstream(upstream, local)}"
        )


def _report(stack: WikiStack, scenario: str) -> None:
    config = stack.config
    print(f"\n  scenario: {scenario} -- {SCENARIOS[scenario]}")
    print(f"  compose project: {config.project_name}")
    for role in stack.roles:
        endpoint = stack.endpoint(role)
        print(f"  {role:9} {endpoint.base_url}/wiki/{CANADIAN_PATENT_INDEX}")
        print(f"  {'':9} api {endpoint.api_url}")
    print(f"  login: {config.username} / {config.password}")
    print("\n  fetch either side into wtbot with, e.g.:\n")
    for role in stack.roles:
        endpoint = stack.endpoint(role)
        print(
            f"    uv run wtbot fetch-page --family harness-{role} --code en"
            f' \\\n        --api-url {endpoint.api_url} "{CANADIAN_PATENT_INDEX}"'
        )
    print("\n  Ctrl-C to exit.\n", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wiki_harness",
        description="Start the two-wiki sync harness and hold it open.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="scenarios:\n"
        + "\n".join(f"  {name:12} {text}" for name, text in SCENARIOS.items()),
    )
    parser.add_argument("--scenario", choices=list(SCENARIOS), default="copied")
    parser.add_argument(
        "--down",
        action="store_true",
        help="tear the stack down on exit instead of leaving it up for reuse",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="destroy any existing volumes first, for a guaranteed-clean install",
    )
    args = parser.parse_args(argv)

    if not docker_available():
        print("no reachable docker daemon", file=sys.stderr)
        return 1

    stack = WikiStack(pair_config())
    if args.rebuild:
        print("removing existing containers and volumes...", flush=True)
        stack.down()

    print("starting the pair (first run installs MediaWiki; be patient)...", flush=True)
    stack.up()
    _build(stack, args.scenario)
    _report(stack, args.scenario)

    # Wait on an Event rather than sleeping in a loop: Ctrl-C is delivered to
    # the main thread immediately, and there is no polling interval to tune.
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass

    if args.down:
        print("\nstopping the stack...", flush=True)
        stack.down()
    else:
        print(
            "\nleaving the stack up. Re-run to reuse it, " "or `--down` to remove it.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
