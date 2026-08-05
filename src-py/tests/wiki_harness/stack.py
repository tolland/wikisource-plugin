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

# Container-side mount of src-py/tests/fixtures (see docker-compose.yml). The
# wikis seed *themselves* from here at startup -- importDump and importImages
# used to be driven from out here, one role at a time, which is exactly how the
# two sides came to hold different content.
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


# Distinct env names from the single-instance fixture's WIKISOURCE_PORT:
# overriding that one must not silently move the pair onto a colliding port.
PAIR_PROJECT = "wtbot-sync-pair"
PAIR_UPSTREAM_PORT = 18581
PAIR_LOCAL_PORT = 18582


def pair_config() -> StackConfig:
    """The two-wiki harness's compose project, from the environment.

    Shared by the pytest fixture and ``python -m wiki_harness`` so that standing
    the pair up by hand and running the tests drive the same containers, volumes
    and ports. Two definitions of this would mean a hand-run stack the tests
    then rebuild from scratch -- MW_SERVER is baked into LocalSettings.php at
    install time, so a volume installed for one port must never be reused on
    another.
    """
    return StackConfig(
        project_name=os.environ.get("SYNC_COMPOSE_PROJECT_NAME", PAIR_PROJECT),
        upstream_port=int(os.environ.get("SYNC_UPSTREAM_PORT", PAIR_UPSTREAM_PORT)),
        local_port=int(os.environ.get("SYNC_LOCAL_PORT", PAIR_LOCAL_PORT)),
        username=os.environ.get("MW_ADMIN_USER", "Admin"),
        password=os.environ.get("MW_ADMIN_PASSWORD", "AdminPassword123!"),
        with_pair=True,
    )


class WikiStack:
    """A compose project holding one or two MediaWiki instances."""

    def __init__(self, config: StackConfig) -> None:
        self.config = config

    # -- endpoints --------------------------------------------------------

    def endpoint(self, role: str = "upstream") -> WikiEndpoint:
        port = (
            self.config.upstream_port if role == "upstream" else self.config.local_port
        )
        # Pywikibot shares an HTTP cookie jar process-wide, and cookies are
        # scoped by hostname rather than port.  Use two names for the loopback
        # interface so logging in to one harness wiki cannot replace the other
        # wiki's session cookie.
        host = "127.0.0.1" if role == "upstream" else "localhost"
        base_url = f"http://{host}:{port}"
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

    def export_dump(self, role: str) -> str:
        """Export every revision so an import can be checked through the same
        portable XML representation as its source dump.
        """
        return self.maintenance(role, "dumpBackup", "--full")


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
