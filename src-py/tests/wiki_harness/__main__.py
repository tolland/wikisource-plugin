import argparse
import sys

from wiki_harness.api import WikiApi
from wiki_harness.scenarios import CANADIAN_PATENT_INDEX, NotSeeded, assert_seeded
from wiki_harness.stack import WikiStack, docker_available, pair_config

"""Bring the two-wiki harness up and report where it is.

    PYTHONPATH=src-py/tests uv run python -m wiki_harness

(the PYTHONPATH is what pytest's ``pythonpath`` ini setting does for the test
run; plain ``python`` has no equivalent.)

There is no ``--scenario`` and nothing to hold open. The wikis seed themselves
from ``SEED_DUMPS``/``SEED_SCANS``, and ``compose up -d`` leaves them running
until something takes them down -- so this is a convenience over

    docker compose --profile pair up -d --wait

that prints the URLs and checks the content actually landed. Differences a test
needs are made by the test, over the API, in a line or two; see
``wiki_harness.scenarios``.
"""


def _report(stack: WikiStack) -> int:
    config = stack.config
    print(f"\n  compose project: {config.project_name}")
    problems = 0
    for role in stack.roles:
        endpoint = stack.endpoint(role)
        api = WikiApi(endpoint)
        api.login()
        try:
            assert_seeded(api, role=role)
            state = "seeded"
        except NotSeeded as exc:
            state = f"NOT SEEDED -- {exc}"
            problems += 1
        print(f"  {role:9} {endpoint.base_url}  [{state}]")
        print(f"  {'':9} {endpoint.base_url}/wiki/{CANADIAN_PATENT_INDEX}")
        print(f"  {'':9} api {endpoint.api_url}")
    print(f"  login: {config.username} / {config.password}")

    print("\n  fetch either side into wtbot with, e.g.:\n")
    for role in stack.roles:
        endpoint = stack.endpoint(role)
        print(
            f"    uv run wtbot fetch-page --family harness-{role} --code en"
            f' \\\n        --api-url {endpoint.api_url} "{CANADIAN_PATENT_INDEX}"'
        )
    print(flush=True)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m wiki_harness",
        description="Bring the two-wiki sync harness up, or report on it.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="up",
        choices=("up", "status", "down"),
        help="up: start and report (default). status: report only. "
        "down: remove containers and volumes.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="destroy existing volumes first, forcing a clean install and reseed",
    )
    args = parser.parse_args(argv)

    if not docker_available():
        print("no reachable docker daemon", file=sys.stderr)
        return 1

    stack = WikiStack(pair_config())

    if args.action == "down":
        stack.down()
        return 0

    if args.action == "up":
        if args.rebuild:
            print("removing existing containers and volumes...", flush=True)
            stack.down()
        print(
            "starting the pair "
            "(a cold start installs MediaWiki and imports; be patient)...",
            flush=True,
        )
        stack.up()

    return 1 if _report(stack) else 0


if __name__ == "__main__":
    raise SystemExit(main())
