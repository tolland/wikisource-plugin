"""Standalone OCR wrapper: a small FastAPI app + client seam over one or
more OCR backends (Wikimedia OCR, a token-guarded vision API, ...).

Deliberately independent of wtbot: nothing here imports wikitext/pywikibot/
MediaWiki concepts, and it needs no wiki credentials to run. A caller
identifies a request only by an ``image_url``/``image_base64`` and an
optional ``scope`` string used to pick which configured backend to use —
wtbot happens to pass a wiki's ``family/code`` as that scope when it embeds
this app, but any other application (an EXIF/metadata tool, a batch OCR
script) can use the same app with its own scopes or none at all.

See ``ocrapi.app.create_ocr_app`` to embed this in another FastAPI process
(as wtbot does, mounted at ``/ocr``) or run it directly:

    uv run fastapi dev src-py/ocrapi/app.py
"""
