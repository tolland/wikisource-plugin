import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests
from wiki_harness import docker_available

from ocrapi.client import OcrError, OcrRequest, WikimediaOcrClient

"""Integration test against a *real* Wikimedia OCR instance
(https://gitlab.wikimedia.org/toolforge-repos/ocr), built from
docker/wikimedia-ocr/Dockerfile, to check WikimediaOcrClient's request
shape and response parsing against the actual service rather than a
hand-written fake of its JSON.

Best-effort and unverified: the Dockerfile was written from the deployment
notes at https://wikitech.wikimedia.org/wiki/Nova_Resource:Wikisource/Wikimedia_OCR
without a chance to build it here. Expect the first local run to need
fixes -- wrong PHP/Node versions, a changed upstream repo layout, a
different document root, etc. That's fine: run

    docker compose --profile ocr build wikimedia-ocr

directly to iterate on the Dockerfile with real build output, then re-run
this test once `docker compose --profile ocr up -d wikimedia-ocr` serves
something on WIKIMEDIA_OCR_PORT.
"""

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose.yml"

# A small, stable, public test image with real printed text -- Testing
# Wikimedia Commons' own OCR sandbox page uses similar fixtures, but any
# world-readable image with recognizable text works here.
SAMPLE_IMAGE_URL = "https://wikisource-debian-13.lan/w/images/thumb/3/31/The_principles_of_mechanics_presented_in_a_new_form_%28Hertz%2C_1894%29.pdf/page7-706px-The_principles_of_mechanics_presented_in_a_new_form_%28Hertz%2C_1894%29.pdf.jpg"


@pytest.fixture(scope="session")
def wikimedia_ocr_url() -> Iterator[str]:
    if not docker_available():
        pytest.skip("A running Docker daemon is required for the Wikimedia OCR harness")

    port = os.environ.get("WIKIMEDIA_OCR_PORT", "8090")
    project_name = os.environ.get(
        "WIKIMEDIA_OCR_COMPOSE_PROJECT_NAME", "wtbot-wikimedia-ocr"
    )
    env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project_name,
        "WIKIMEDIA_OCR_PORT": port,
    }
    compose = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "ocr"]
    # A pytest CLI flag would need registering in conftest.py; an env var
    # keeps this harness self-contained in one file, same trade-off the
    # rest of this module makes.
    reuse = os.environ.get("WIKIMEDIA_OCR_REUSE") == "1"

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
            [*compose, "up", "--build", "-d", "wikimedia-ocr"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"failed to start the Wikimedia OCR container: {exc}")

    base_url = f"http://127.0.0.1:{port}"
    _wait_for_ocr_service(base_url)

    yield base_url

    if not reuse:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )


def _wait_for_ocr_service(base_url: str, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                f"{base_url}/api.php",
                params={"image": SAMPLE_IMAGE_URL, "engine": "tesseract"},
                timeout=10,
            )
            # Any HTTP response (even a documented error body) means the
            # app booted; only connection failures should keep retrying.
            if resp.status_code < 500:
                return
            last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(3)

    raise TimeoutError(
        f"Wikimedia OCR did not become ready at {base_url}: {last_error}"
    )


@pytest.mark.slow
def test_wikimedia_ocr_recognizes_sample_image(wikimedia_ocr_url: str) -> None:
    client = WikimediaOcrClient(wikimedia_ocr_url)
    result = client.recognize(
        OcrRequest(image_url=SAMPLE_IMAGE_URL, engine="tesseract", langs=["en"])
    )
    assert result.text.strip(), "expected non-empty recognized text"


@pytest.mark.slow
def test_wikimedia_ocr_unknown_engine_raises(wikimedia_ocr_url: str) -> None:
    client = WikimediaOcrClient(wikimedia_ocr_url)
    with pytest.raises(OcrError):
        client.recognize(
            OcrRequest(image_url=SAMPLE_IMAGE_URL, engine="not-a-real-engine")
        )
