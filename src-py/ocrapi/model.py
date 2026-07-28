from datetime import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""OCR backend configuration — deliberately scoped by a plain string, not a
foreign key into anyone's site/tenant table, so this table (and this whole
package) never needs to know what a "wiki" is. A caller that wants several
independent configurations (e.g. wtbot, one scope per wiki family/code)
picks its own scope strings; a caller with exactly one deployment can leave
``scope`` at its default and never think about it again.

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
"""


class OcrBackendKind(StrEnum):
    wikimedia = "wikimedia"
    token_api = "token_api"


DEFAULT_SCOPE = "default"


class OcrBackendConfig(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("scope", "name", name="uq_ocr_backend_scope_name"),
    )

    pk: int | None = Field(default=None, primary_key=True)

    # A caller-chosen namespace for its backends, e.g. a wiki "family/code"
    # pair, an app name, or just the default — never a foreign key, so this
    # table has no dependency on any other schema.
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
