from datetime import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Per-site OCR backend configuration.

Public Wikisource uses Wikimedia OCR (https://ocr.wmcloud.org), but that
service is not reachable from (or aware of) self-hosted wikis, so each Site
carries its own OCR backend rows: the API base URL plus whatever metadata
the backend needs (token, default engine/languages, a default prompt for
prompt-driven vision backends). A site may configure several backends —
e.g. a Wikimedia-OCR instance for plain text and a token-guarded vision
API for pages with idiosyncratic typesetting — and the client picks per
request.

``kind`` selects the wire protocol (see wtbot.ocr.build_client, the
extension point where alternative backends plug in):

- ``wikimedia`` — the Wikimedia OCR HTTP API (GET /api.php?engine=&langs[]=
  &image=). URL-driven: the service fetches the image itself, so requests
  carry a wiki-reachable image URL, never client-local bytes.
- ``token_api`` — a generic bearer-token JSON vision API (POST base_url
  with {image_base64, prompt, langs}); the shape a Gemini-style adapter
  sits behind. Segment-driven: requests carry the cropped region's bytes
  and an optional prompt (e.g. custom LaTeX instructions for 19th-century
  typesetting).
"""


class OcrBackendKind(StrEnum):
    wikimedia = "wikimedia"
    token_api = "token_api"


class OcrBackendConfig(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("site_pk", "name", name="uq_ocr_backend_site_name"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk", index=True)

    name: str  # human-chosen handle, e.g. "wmocr", "gemini"
    kind: OcrBackendKind
    base_url: str  # e.g. "https://ocr.wikisource-debian-13.lan"

    api_token: str | None = None
    # "tesseract" is Wikimedia OCR's free/local engine — "google" costs
    # money, so a config that doesn't say otherwise should not silently
    # incur charges.
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
