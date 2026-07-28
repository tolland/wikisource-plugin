from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session


def get_ocr_session(request: Request) -> Iterator[Session]:
    """Yield a Session bound to the engine stored on app.state — mirrors
    wtbot.deps.get_session, independently, so this package needs no import
    from wtbot. Tests swap the engine by building the app with a different
    one (see ocrapi.app.create_ocr_app)."""
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session
