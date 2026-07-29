"""OCR wrapper: a small FastAPI app + client seam over one or more OCR
backends (Wikimedia OCR, a token-guarded vision API, ...), factored out of
wtbot so its HTTP surface and client logic are reusable and independently
testable — but its persisted config (``wtbot.model.ocr_backend
.OcrBackendConfig``) is wtbot's own app state, tracked by wtbot's Alembic
migrations and living in wtbot's shared database file, not a schema this
package owns.

A caller identifies a recognition request only by an
``image_url``/``image_base64`` and an optional ``scope`` string used to
pick which configured backend to use — wtbot passes a wiki's
``family/code`` as that scope when it embeds this app (see
wtbot.api.ocr), but any other grouping works too, including none (the
default scope).

See ``ocrapi.app.create_ocr_app`` to embed this in another FastAPI process
(as wtbot does, mounted at ``/ocr``) or run it directly against wtbot's
database:

    uv run fastapi dev src-py/ocrapi/dev_server.py
"""
