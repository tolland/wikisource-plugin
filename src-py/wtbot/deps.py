from collections.abc import Iterator

from fastapi import Request
from sqlmodel import Session


def get_session(request: Request) -> Iterator[Session]:
    """Yield a Session bound to the engine stored on app.state. Tests swap the
    engine by building the app with a different one (see create_app)."""
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session
