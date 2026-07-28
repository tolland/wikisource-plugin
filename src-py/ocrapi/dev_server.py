from ocrapi.app import create_ocr_app

"""Standalone dev entry point: `uv run fastapi dev src-py/ocrapi/dev_server.py`.
Backed by its own on-disk `ocr.db` in the working directory (see
ocrapi.db.DEFAULT_SQLITE_URL) — the one place that file gets created."""

app = create_ocr_app()
