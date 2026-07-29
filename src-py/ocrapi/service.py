from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from ocrapi.client import OcrClient, OcrRequest, OcrResult, build_client
from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind

"""Framework-agnostic core: everything ocrapi's own router (scope from a
query param) and a host's own scoped routes (wtbot's page-scoped /pages/ocr,
scope = wiki family/code) both need. Neither caller talks to OcrBackendConfig
or OcrClient directly — this module is the one seam, so a future storage
backend or a batching layer only has to change here.
"""

ClientBuilder = Callable[[OcrBackendConfig], OcrClient]


class _UnsetType:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _UnsetType()
"""Sentinel for [upsert_backend]'s ``api_token``: distinguishes "the caller
didn't mention the token, leave it alone" (UNSET, the default) from
"the caller explicitly wants it cleared" (None) -- an edit form can safely
leave its write-only token field blank without clobbering a stored secret."""


@dataclass(slots=True)
class UnknownBackend(Exception):
    scope: str
    name: str | None = None

    def __str__(self) -> str:
        if self.name is None:
            return f"no OCR backend configured for scope {self.scope!r}"
        return f"no enabled OCR backend {self.name!r} for scope {self.scope!r}"


def list_backends(
    session: Session, scope: str, *, enabled_only: bool = True
) -> list[OcrBackendConfig]:
    stmt = select(OcrBackendConfig).where(OcrBackendConfig.scope == scope)
    if enabled_only:
        stmt = stmt.where(OcrBackendConfig.enabled == True)  # noqa: E712
    stmt = stmt.order_by(OcrBackendConfig.pk)
    return list(session.exec(stmt).all())


def get_backend(session: Session, scope: str, name: str) -> OcrBackendConfig | None:
    return session.exec(
        select(OcrBackendConfig).where(
            OcrBackendConfig.scope == scope, OcrBackendConfig.name == name
        )
    ).first()


def upsert_backend(
    session: Session,
    scope: str,
    name: str,
    *,
    kind: OcrBackendKind,
    base_url: str,
    api_token: str | None | _UnsetType = UNSET,
    default_engine: str | None = "tesseract",
    default_langs: list[str] | None = None,
    default_prompt: str | None = None,
    enabled: bool = True,
) -> OcrBackendConfig:
    row = get_backend(session, scope, name)
    if row is None:
        row = OcrBackendConfig(scope=scope, name=name, kind=kind, base_url=base_url)
    row.kind = kind
    row.base_url = base_url
    if api_token is not UNSET:
        row.api_token = api_token
    row.default_engine = default_engine
    row.default_langs = ",".join(default_langs) if default_langs else None
    row.default_prompt = default_prompt
    row.enabled = enabled
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_backend(session: Session, scope: str, name: str) -> bool:
    row = get_backend(session, scope, name)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def resolve_backend(session: Session, scope: str, name: str | None) -> OcrBackendConfig:
    """The backend named [name], or the scope's first enabled backend when
    None. Raises UnknownBackend (never HTTPException — callers map that)."""
    if name is not None:
        row = get_backend(session, scope, name)
        if row is None or not row.enabled:
            raise UnknownBackend(scope, name)
        return row
    backends = list_backends(session, scope)
    if not backends:
        raise UnknownBackend(scope)
    return backends[0]


def recognize(
    session: Session,
    scope: str,
    request: OcrRequest,
    *,
    backend_name: str | None = None,
    client_builder: ClientBuilder = build_client,
) -> tuple[OcrBackendConfig, OcrResult]:
    """Resolves the backend for [scope]/[backend_name], fills request
    defaults (engine/langs/prompt) from its config, and runs recognition.
    Raises UnknownBackend or OcrError; callers map both to HTTP errors."""
    config = resolve_backend(session, scope, backend_name)
    filled = OcrRequest(
        image_url=request.image_url,
        crop=request.crop,
        image_base64=request.image_base64,
        engine=request.engine or config.default_engine,
        langs=request.langs if request.langs else config.langs_list(),
        prompt=request.prompt or config.default_prompt,
    )
    result = client_builder(config).recognize(filled)
    return config, result
