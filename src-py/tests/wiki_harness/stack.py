import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from wiki_harness.endpoint import WikiEndpoint

"""docker-compose lifecycle for the harness wikis.

One ``WikiStack`` owns a compose project; a project may hold one wiki
(``upstream`` only) or two (``upstream`` + ``local``, via the ``pair`` profile).
Maintenance scripts run inside the container, which is how fixtures with real
revision history get seeded -- importDump.php preserves per-revision text,
timestamps, contributors and therefore sha1, which no API-level copy does.
"""

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# Container-side mount of src-py/tests/fixtures (see docker-compose.yml).
FIXTURES_MOUNT = "/fixtures"

SERVICE_FOR_ROLE = {"upstream": "mediawiki", "local": "mediawiki-local"}
DB_SERVICE_FOR_ROLE = {"upstream": "db", "local": "db-local"}


def docker_available() -> bool:
    """True only when a docker *daemon* is reachable.

    ``shutil.which("docker")`` is not enough: the CLI is frequently installed
    where no daemon runs, and that turns every harness test into a fixture
    error rather than a skip.
    """
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@dataclass(frozen=True)
class StackConfig:
    project_name: str
    upstream_port: int
    local_port: int
    username: str = "Admin"
    password: str = "AdminPassword123!"
    with_pair: bool = False


class WikiStack:
    """A compose project holding one or two MediaWiki instances."""

    def __init__(self, config: StackConfig) -> None:
        self.config = config

    # -- endpoints --------------------------------------------------------

    def endpoint(self, role: str = "upstream") -> WikiEndpoint:
        port = (
            self.config.upstream_port if role == "upstream" else self.config.local_port
        )
        base_url = f"http://127.0.0.1:{port}"
        return WikiEndpoint(
            role=role,
            base_url=base_url,
            api_url=f"{base_url}/api.php",
            username=self.config.username,
            password=self.config.password,
        )

    # -- compose ----------------------------------------------------------

    @property
    def _env(self) -> dict[str, str]:
        return {
            **os.environ,
            "COMPOSE_PROJECT_NAME": self.config.project_name,
            "MW_ADMIN_USER": self.config.username,
            "MW_ADMIN_PASSWORD": self.config.password,
            "WIKISOURCE_PORT": str(self.config.upstream_port),
            "WIKISOURCE_LOCAL_PORT": str(self.config.local_port),
        }

    def _compose(self, *args: str) -> list[str]:
        base = ["docker", "compose", "-f", str(COMPOSE_FILE)]
        if self.config.with_pair:
            base += ["--profile", "pair"]
        return [*base, *args]

    def up(self) -> None:
        subprocess.run(
            self._compose("up", "--build", "-d"),
            cwd=REPO_ROOT,
            env=self._env,
            check=True,
        )
        for role in self.roles:
            wait_for_mediawiki(self.endpoint(role).api_url)

    def down(self) -> None:
        subprocess.run(
            self._compose("down", "--volumes", "--remove-orphans"),
            cwd=REPO_ROOT,
            env=self._env,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @property
    def roles(self) -> tuple[str, ...]:
        return ("upstream", "local") if self.config.with_pair else ("upstream",)

    # -- in-container maintenance ----------------------------------------

    def maintenance(
        self, role: str, script: str, *args: str, timeout: int = 900
    ) -> str:
        """Run ``maintenance/run.php <script>`` in the given wiki's container."""
        command = self._compose(
            "exec",
            "-T",
            SERVICE_FOR_ROLE[role],
            "php",
            "maintenance/run.php",
            script,
            *args,
        )
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=self._env,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            print("\n--- command failed ---")
            print("command:", exc.cmd)
            print("exit code:", exc.returncode)

            if exc.stdout:
                print("\n--- stdout ---")
                print(exc.stdout)

            if exc.stderr:
                print("\n--- stderr ---")
                print(exc.stderr)

            raise
        return completed.stdout

    def sql(self, role: str, query: str, *, timeout: int = 120) -> list[dict[str, str]]:
        """Run a read query against the wiki's MariaDB and return rows as dicts.

        The point of having the database is that ``content_sha1`` and
        ``content_size`` -- the values MediaWiki actually hashes and measures --
        are not exposed by any read API. Reading them settles what the served
        serialization can only be inferred from.
        """
        command = self._compose(
            "exec",
            "-T",
            DB_SERVICE_FOR_ROLE[role],
            "mariadb",
            "-umediawiki",
            "-pmediawiki",
            "--batch",
            "--raw",
            "-e",
            query,
            "mediawiki",
        )
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=self._env,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        lines = [ln for ln in completed.stdout.splitlines() if ln.strip()]
        if not lines:
            return []
        headers = lines[0].split("\t")
        return [dict(zip(headers, ln.split("\t"), strict=False)) for ln in lines[1:]]

    def import_dump(self, role: str, dump_name: str) -> str:
        """Import an XML dump from the mounted fixtures directory.

        ``--uploads`` is deliberately not passed: the dumps carry page text
        only, and the backing scan is imported separately by
        :meth:`import_scan`.
        """
        return self.maintenance(
            role,
            "importDump",
            "--no-updates",
            f"{FIXTURES_MOUNT}/scans/{dump_name}",
        )

    def import_scans(self, role: str, extension: str = "djvu") -> str:
        """Upload every scan of the given extension from the fixtures mount.

        importImages takes a directory, deriving each File: title from the
        filename (underscores become spaces), so
        ``Canadian_patent_29537.djvu`` lands as
        ``File:Canadian patent 29537.djvu`` -- matching the title the dumps
        reference.
        """
        return self.maintenance(
            role,
            "importImages",
            "--comment=harness scan import",
            f"--extensions={extension}",
            f"{FIXTURES_MOUNT}/scans",
        )

    def rebuild_links(self, role: str) -> None:
        """importDump --no-updates skips link/category tables; ProofreadPage's
        index pagination needs them populated."""
        self.maintenance(role, "rebuildall")


def wait_for_mediawiki(api_url: str, timeout_seconds: int = 300) -> None:
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
    raise TimeoutError(f"MediaWiki API not ready at {api_url}: {last_error}")
