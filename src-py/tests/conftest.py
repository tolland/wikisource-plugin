import logging
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
COMPOSE_FILE = REPO_ROOT / "compose.yml"

# Re-exported: several tests import these from conftest, and wiki_harness owns
# them so `python -m wiki_harness` builds the same fixture the tests assert on.
__all__ = ["CANADIAN_PATENT_INDEX", "CANADIAN_PATENT_SCAN"]


def pytest_addoption(parser: pytest.Parser) -> None:
    logging.getLogger("alembic.runtime.migration").setLevel(logging.WARNING)
    parser.addoption(
        "--reuse-wikisource",
        action="store_true",
        help="Keep and reuse the docker-compose Wikisource stack between test runs.",
    )
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


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


def drain(client: TestClient, **kwargs) -> dict:
    """Work the fetch queue and return the drain report.

    Enqueueing no longer fetches (see wtbot.api.fetch), so a test that wants a
    page in the database has to ask for the fetch to happen -- exactly as a
    caller does. Kept as a plain helper rather than an autouse fixture on
    purpose: which tests drain, and *when* they drain relative to a read, is
    the thing several of these tests are about.
    """
    resp = client.post("/fetch/drain", json=kwargs or None)
    resp.raise_for_status()
    return resp.json()


def register_site(
    client: TestClient,
    *,
    label: str = "test",
    family: str = "mywikisource",
    code: str = "en",
    api_url: str | None = None,
    username: str | None = "Admin",
    password: str = "harness-password",
    bot_name: str | None = None,
) -> dict:
    """Register a site the way an operator does, and return the row.

    Credentialed by default, because wtbot is: fetching refuses a site that
    cannot log in (see site_store.require_credentialed_site), so a test that
    registered a bare site would be exercising a configuration the product
    rejects. Pass ``username=None`` for the tests that are *about* that refusal.

    Nothing conjures a site from a fetch request's parameters any more, so
    tests go through the same door an operator does.
    """
    resp = client.post(
        "/sites/",
        json={"label": label, "family": family, "code": code, "api_url": api_url},
    )
    resp.raise_for_status()
    site = resp.json()

    if username is not None:
        credential = client.put(
            f"/sites/{site['pk']}/credential",
            json={"username": username, "password": password, "bot_name": bot_name},
        )
        credential.raise_for_status()
    return site


def credential_for(session: Session, site) -> None:
    """Give a directly-built Site row an account.

    The API-level helper above goes through PUT /sites/{pk}/credential;
    fixtures that build a Site with the ORM need the same, because the fetch
    endpoints refuse a site that cannot log in.
    """
    from wtbot.model import SiteCredential

    session.add(
        SiteCredential(site_pk=site.pk, username="Admin", password="harness-password")
    )
    session.commit()


def fetch_and_drain(client: TestClient, payload: dict) -> dict:
    """Enqueue a fetch, run it, and report as the old inline endpoint did:
    ``{"request": ..., "page": ...}`` with both read back *after* the drain."""
    enqueued = client.post("/fetch/", json=payload)
    enqueued.raise_for_status()
    request_pk = enqueued.json()["request"]["pk"]

    drain(client)

    request = client.get(f"/fetch/{request_pk}")
    request.raise_for_status()
    site = client.get(f"/sites/by-label/{payload['label']}").json()
    page = client.get(
        "/pages/resolve",
        params={
            "family": site["family"],
            "code": site["code"],
            "title": payload["title"],
        },
    )
    return {
        "request": request.json(),
        "page": page.json() if page.status_code == 200 else None,
    }


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
