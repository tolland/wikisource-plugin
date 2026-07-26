import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from wtbot.db import create_db_engine, init_db
from wtbot.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"


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


@pytest.fixture(scope="session")
def wikisource(pytestconfig: pytest.Config) -> Iterator[WikisourceInstance]:
    """Start a minimal MediaWiki/Wikisource stack for e2e tests."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for Wikisource e2e tests")

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
