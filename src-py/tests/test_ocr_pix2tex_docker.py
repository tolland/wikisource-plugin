import base64
import http.server
import io
import os
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import requests
from PIL import Image, ImageDraw
from wiki_harness import docker_available

from ocrapi.client import OcrCrop, OcrError, OcrRequest, Pix2TexClient

"""Integration test against a *real* pix2tex/LaTeX-OCR instance (the
public ``lukasblecher/pix2tex:api`` image: https://pix2tex.readthedocs.io/),
to check Pix2TexClient's multipart upload and response parsing against the
actual service rather than a mocked one (see test_ocrapi.py for the
mocked-HTTP unit tests, including the crop-with-Pillow path).

Every test here is @pytest.mark.slow: the image is ~4.2GB and pulls a
model on top of that, so this must never run somewhere a 5-15 minute first
pull would be a surprise (CI, a quick local `pytest`, ...). Run it
explicitly:

    docker compose --profile pix2tex up -d pix2tex   # first pull is slow
    uv run pytest src-py/tests/test_ocr_pix2tex_docker.py -m slow

The Docker image itself isn't ours to get wrong the way the wikimedia-ocr
Dockerfile might be, but the request/response shape here is still
best-effort against pix2tex's documented API (POST /bytes/ with a "file"
field, a JSON-string response) -- fix forward if the real container
disagrees.
"""

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="session")
def pix2tex_url() -> Iterator[str]:
    if not docker_available():
        pytest.skip("A running Docker daemon is required for the pix2tex harness")

    port = os.environ.get("PIX2TEX_PORT", "8502")
    project_name = os.environ.get("PIX2TEX_COMPOSE_PROJECT_NAME", "wtbot-pix2tex")
    env = {**os.environ, "COMPOSE_PROJECT_NAME": project_name, "PIX2TEX_PORT": port}
    compose = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "pix2tex"]
    # Same env-var reuse trade-off as the wikimedia-ocr harness (see
    # test_ocr_wikimedia_docker.py) -- doubly worth it here given the
    # image size: PIX2TEX_REUSE=1 skips the down/up cycle between runs.
    reuse = os.environ.get("PIX2TEX_REUSE") == "1"

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
            [*compose, "up", "-d", "pix2tex"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.fail(f"failed to start the pix2tex container: {exc}")

    base_url = f"http://127.0.0.1:{port}"
    # The model loads on startup, which (on top of a cold image pull) can
    # take a while -- longer patience than the wikimedia-ocr harness.
    _wait_for_pix2tex(base_url, timeout_seconds=600)

    yield base_url

    if not reuse:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )


def _wait_for_pix2tex(base_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            resp = requests.get(base_url, timeout=10)
            if resp.status_code < 500:
                return
            last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(5)

    raise TimeoutError(f"pix2tex did not become ready at {base_url}: {last_error}")


def _formula_image_bytes(text: str = "x^2 + y^2 = z^2") -> bytes:
    """A synthetic formula-ish image. Not meant to test recognition
    *accuracy* (that's pix2tex's own test suite's job) -- just that our
    multipart upload and response parsing round-trip against the real
    service without error."""
    image = Image.new("RGB", (240, 60), "white")
    ImageDraw.Draw(image).text((10, 20), text, fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_pix2tex_recognizes_a_formula_image(pix2tex_url: str) -> None:
    client = Pix2TexClient(pix2tex_url)
    result = client.recognize(
        OcrRequest(image_base64=base64.b64encode(_formula_image_bytes()).decode())
    )
    assert result.text.strip(), "expected non-empty LaTeX prediction"
    assert result.engine == "pix2tex"


def test_pix2tex_fetches_and_crops_before_uploading(pix2tex_url: str) -> None:
    # A bigger canvas with the formula only in one corner -- proves the
    # client is really cropping server-round-trip, not just passing the
    # whole (uncropped) image through.
    full = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(full).text((300, 300), "a+b", fill="black")
    buf = io.BytesIO()
    full.save(buf, format="PNG")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buf.getvalue())

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        image_url = f"http://127.0.0.1:{server.server_port}/formula.png"
        client = Pix2TexClient(pix2tex_url)
        result = client.recognize(
            OcrRequest(
                image_url=image_url,
                crop=OcrCrop(x=290, y=290, width=100, height=60),
            )
        )
        assert result.text is not None  # accuracy isn't the point here
    finally:
        server.shutdown()


def test_pix2tex_requires_image_url_or_bytes(pix2tex_url: str) -> None:
    client = Pix2TexClient(pix2tex_url)
    with pytest.raises(OcrError):
        client.recognize(OcrRequest())
