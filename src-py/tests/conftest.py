import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session
from wiki_harness import (
    CANADIAN_PATENT_INDEX,
    CANADIAN_PATENT_SCAN,
    PwbHarness,
    WikiApi,
    WikiStack,
    assert_seeded,
    docker_available,
    pair_config,
    pywikibot_harness,
)

from wtbot.db import create_db_engine, init_db
from wtbot.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose.seeded.yml"

# Re-exported: several tests import these from conftest, and wiki_harness owns
# them so `python -m wiki_harness` builds the same fixture the tests assert on.
__all__ = ["CANADIAN_PATENT_INDEX", "CANADIAN_PATENT_SCAN"]


@dataclass(frozen=True)
class WikisourceInstance:
    base_url: str
    api_url: str
    username: str
    password: str


@pytest.fixture
def engine(tmp_path) -> Engine:
    """A throwaway file-backed SQLite engine (file-backed so WAL behaves like
    production, not :memory:). Tables are created fresh per test."""
    db_path = tmp_path / "test.db"
    eng = create_db_engine(f"sqlite:///{db_path}")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine=engine)
    with TestClient(app) as c:
        yield c


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--reuse-wikisource",
        action="store_true",
        help="Keep and reuse the docker-compose Wikisource stack between test runs.",
    )


# --------------------------------------------------------------------------
# Two-wiki harness (upstream + local) for cross-wiki sync tests.
#
# Separate compose project and ports from the single-instance `wikisource`
# fixture above: MW_SERVER is baked into LocalSettings.php at install time, so a
# volume installed for one port must never be reused on another.
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def wiki_pair(pytestconfig: pytest.Config) -> Iterator[WikiStack]:
    """Two MediaWiki+ProofreadPage instances holding the same works.

    `upstream` stands in for en.wikisource.org, `local` for the staging wiki.
    Both seed themselves from the same compose anchor, so the pair starts
    *converged* and any difference between them was made on purpose.

    The compose project comes from ``pair_config()`` so that
    ``python -m wiki_harness`` drives the very same containers.
    """
    if not docker_available():
        pytest.skip("A running Docker daemon is required for the two-wiki harness")

    stack = WikiStack(pair_config())
    reuse = pytestconfig.getoption("--reuse-wikisource")

    if not reuse:
        stack.down()

    try:
        stack.up()
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"failed to start the two-wiki harness: {exc}")
    yield stack

    if not reuse:
        stack.down()


@pytest.fixture(scope="session")
def upstream_api(wiki_pair: WikiStack) -> WikiApi:
    api = WikiApi(wiki_pair.endpoint("upstream"))
    api.login()
    return api


@pytest.fixture(scope="session")
def local_api(wiki_pair: WikiStack) -> WikiApi:
    api = WikiApi(wiki_pair.endpoint("local"))
    api.login()
    return api


# Ordinary accounts for edit tests. The admin is a sysop and carries rights
# that change what MediaWiki permits, so running edit tests as admin can hide
# rejections a normal bot account would hit. `Promoter` stands in for the
# account a promotion batch would push as; `Bystander` for anyone else editing
# the same page.
HARNESS_PASSWORD = "HarnessAccountPassword123!"


def _editor(wiki_pair: WikiStack, role: str, username: str) -> WikiApi:
    admin = WikiApi(wiki_pair.endpoint(role))
    admin.login()
    admin.create_account(username, HARNESS_PASSWORD)

    api = WikiApi(
        replace(wiki_pair.endpoint(role), username=username, password=HARNESS_PASSWORD)
    )
    api.login()
    return api


@pytest.fixture(scope="session")
def local_promoter(wiki_pair: WikiStack) -> WikiApi:
    """Ordinary account standing in for the promotion bot."""
    return _editor(wiki_pair, "local", "Promoter")


@pytest.fixture(scope="session")
def local_bystander(wiki_pair: WikiStack) -> WikiApi:
    """A *different* ordinary account.

    Conflict tests need two distinct users: EditPage suppresses conflicts when
    the requesting user made every intervening revision.
    """
    return _editor(wiki_pair, "local", "Bystander")


@pytest.fixture(scope="session")
def upstream_pwb(wiki_pair: WikiStack) -> PwbHarness:
    """pywikibot bound to the upstream harness wiki.

    The production fetch path is pywikibot, so revision claims should be
    assertable through the same library the worker uses.
    """
    return pywikibot_harness(wiki_pair.endpoint("upstream"))


@pytest.fixture(scope="session")
def local_pwb(wiki_pair: WikiStack) -> PwbHarness:
    return pywikibot_harness(wiki_pair.endpoint("local"))


@pytest.fixture(scope="session")
def seeded_upstream(upstream_api: WikiApi) -> WikiApi:
    """Upstream, confirmed to hold the real Canadian patent work: the backing
    DjVu, the Index:, its 24 Page: subpages with full revision history, and the
    template and Module: closure needed for them to render.

    It no longer *does* the seeding -- the container does, from ``SEED_DUMPS``,
    and so does the local wiki from the same compose anchor. This fixture only
    asserts it happened, because a test that quietly seeds one side is how the
    two wikis came to differ before anyone diverged them on purpose.

    Imported rather than API-written on purpose: importDump preserves each
    revision's text, timestamp and contributor, and recomputes sha1 from the
    text it stores. An API copy would flatten history to a single revision --
    which is a situation the tests also want, and build explicitly via
    ``copy_page_to_local``.
    """
    return assert_seeded(upstream_api, role="upstream")


@pytest.fixture(scope="session")
def seeded_local(local_api: WikiApi) -> WikiApi:
    """The local wiki, holding the same work as upstream.

    The symmetric counterpart, and the fixture whose absence was the bug: with
    only ``seeded_upstream`` there was no way to say "both sides start equal",
    so "diverged" meant "never converged".
    """
    return assert_seeded(local_api, role="local")


@pytest.fixture(scope="session")
def wikisource(pytestconfig: pytest.Config) -> Iterator[WikisourceInstance]:
    """Start a minimal MediaWiki/Wikisource stack for e2e tests."""
    if not docker_available():
        pytest.skip("A running Docker daemon is required for Wikisource e2e tests")

    port = os.environ.get("WIKISOURCE_PORT", "8080")
    project_name = os.environ.get("COMPOSE_PROJECT_NAME", "wikibot-e2e")
    username = os.environ.get("MW_ADMIN_USER", "Admin")
    password = os.environ.get("MW_ADMIN_PASSWORD", "AdminPassword123!")
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project_name,
        "MW_ADMIN_USER": username,
        "MW_ADMIN_PASSWORD": password,
        "WIKISOURCE_PORT": port,
    }
    compose = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    reuse = pytestconfig.getoption("--reuse-wikisource")

    if not reuse:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    try:
        subprocess.run(
            [*compose, "up", "--build", "-d"], cwd=REPO_ROOT, env=env, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"failed to start Wikisource docker-compose stack: {exc}")

    instance = WikisourceInstance(
        base_url=f"http://127.0.0.1:{port}",
        api_url=f"http://127.0.0.1:{port}/api.php",
        username=username,
        password=password,
    )
    _wait_for_mediawiki(instance.api_url)

    yield instance

    if not reuse:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )


def _wait_for_mediawiki(api_url: str, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(
                api_url,
                params={
                    "action": "query",
                    "meta": "siteinfo",
                    "siprop": "extensions",
                    "format": "json",
                },
                timeout=5,
            )
            response.raise_for_status()
            extensions = response.json()["query"]["extensions"]
            if any(ext["name"] == "ProofreadPage" for ext in extensions):
                return
        except (KeyError, requests.RequestException, ValueError) as exc:
            last_error = exc

        time.sleep(3)

    raise TimeoutError(f"MediaWiki API did not become ready at {api_url}: {last_error}")
