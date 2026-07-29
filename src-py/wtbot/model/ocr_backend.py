from datetime import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""OCR backend configuration — part of wtbot's own app state (this file's
row class is the thing Alembic tracks and wtbot's shared database.db
stores), even though the HTTP surface and client logic that use it
(src-py/ocrapi) are factored out for reuse.

Scoped by a plain string, not a foreign key into Site, so a config row
doesn't require a Site to exist and the ocrapi layer that queries this
table doesn't need to know what a "wiki" is — wtbot happens to pass a
site's family/code pair as scope (see wtbot.api.ocr), but any other
grouping works too.

``kind`` selects the wire protocol (see ocrapi.client.build_client, the
extension point where alternative backends plug in):

- ``wikimedia`` — the Wikimedia OCR HTTP API (GET /api.php?engine=&langs[]=
  &image=&crop[...]=). URL-driven: the service fetches the image itself
  (and can crop server-side), so requests carry a URL the service can
  reach, never client-local bytes.
- ``token_api`` — a generic bearer-token JSON vision API (POST base_url
  with {image_base64, prompt, langs}); the shape a Gemini-style adapter
  sits behind. Segment-driven: requests carry the (already cropped)
  region's bytes and an optional prompt (e.g. custom LaTeX instructions
  for idiosyncratic typesetting).
- ``pix2tex`` — a self-hosted pix2tex/LaTeX-OCR instance (the
  ``lukasblecher/pix2tex:api`` image), a free/local model specialized on
  mathematical notation. Segment-driven like token_api, but multipart file
  upload rather than a JSON body, no prompt (the model isn't
  instructable), and no server-side cropping — the wrapper crops with
  Pillow before uploading when it's given a URL + crop instead of
  pre-cropped bytes.
"""


class OcrBackendKind(StrEnum):
    wikimedia = "wikimedia"
    token_api = "token_api"
    pix2tex = "pix2tex"


DEFAULT_SCOPE = "default"


class OcrBackendConfig(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("scope", "name", name="uq_ocr_backend_scope_name"),
    )

    pk: int | None = Field(default=None, primary_key=True)

    # A caller-chosen namespace for its backends, e.g. a wiki "family/code"
    # pair, an app name, or just the default — never a foreign key, so a
    # config row doesn't require its Site (or anything else) to exist.
    scope: str = Field(default=DEFAULT_SCOPE, index=True)

    name: str  # human-chosen handle, e.g. "wmocr", "gemini"
    kind: OcrBackendKind
    base_url: str  # e.g. "https://ocr.wikisource-debian-13.lan"

    api_token: str | None = None
    # "tesseract" is Wikimedia OCR's free/local engine — "google" costs
    # money, so a config that doesn't say otherwise defaults there rather
    # than to a paid engine.
    default_engine: str | None = "tesseract"
    default_langs: str | None = None  # comma-separated, e.g. "en,de"
    default_prompt: str | None = None  # prompt-driven backends only

    enabled: bool = True

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def langs_list(self) -> list[str]:
        return [
            lang.strip()
            for lang in (self.default_langs or "").split(",")
            if lang.strip()
        ]
