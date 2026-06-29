"""VCR configuration shared across test_vcr_fetch.py.

Import `make_vcr` to get a configured VCR instance, and use `cassette_path`
to resolve cassette files relative to the cassettes/ directory.

Recording workflow (run on a machine with real wiki access):
    VCR_RECORD_MODE=all uv run pytest src-py/tests/test_vcr_fetch.py -v

CI / offline playback:
    uv run pytest src-py/tests/test_vcr_fetch.py -v   # default: mode=none
"""

from __future__ import annotations

import os
from pathlib import Path

import vcr as vcrlib

CASSETTES_DIR = Path(__file__).parent / "cassettes"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# VCR_RECORD_MODE values: none (default), new_episodes, all
RECORD_MODE = os.environ.get("VCR_RECORD_MODE", "none")


def _stub_binary_response(response: dict) -> dict:
    """Replace binary bodies with a small sentinel so cassettes stay YAML-friendly.

    The actual file SHA1, size, and MIME come from the imageinfo API call (JSON),
    not from the download body — so stubbing the download is safe for our tests.
    """
    content_type = ""
    for key, val in (response.get("headers") or {}).items():
        if key.lower() == "content-type":
            content_type = (val[0] if isinstance(val, list) else val).lower()
            break
    # Preserve JSON and plain-text responses; stub everything binary.
    is_text = any(
        t in content_type
        for t in ("application/json", "text/", "application/x-www-form-urlencoded")
    )
    if not is_text and content_type:
        response["body"]["string"] = b"<BINARY_STUB>"
    return response


def make_vcr(subdir: str) -> vcrlib.VCR:
    """Return a configured VCR instance whose cassettes live in cassettes/{subdir}/."""
    return vcrlib.VCR(
        cassette_library_dir=str(CASSETTES_DIR / subdir),
        record_mode=RECORD_MODE,
        before_record_response=_stub_binary_response,
        filter_headers=["Authorization", "Cookie", "Set-Cookie"],
        filter_post_data_parameters=["lgpassword", "lgtoken"],
        # Match on everything except the Host header so recordings from one
        # machine replay on another even if IP differs.
        match_on=["method", "scheme", "host", "port", "path", "query"],
        serializer="yaml",
    )


def cassette_path(subdir: str, name: str) -> Path:
    return CASSETTES_DIR / subdir / f"{name}.yaml"


def cassette_exists(subdir: str, name: str) -> bool:
    return cassette_path(subdir, name).exists()
