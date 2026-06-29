from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlmodel import Session

from wtbot.db import create_db_engine, init_db
from wtbot.main import create_app


@pytest.fixture
def engine(tmp_path) -> Engine:
    """A throwaway file-backed SQLite engine (file-backed so WAL behaves like
    production, not :memory:). Tables are created fresh per test."""
    db_path = tmp_path / "test.db"
    eng = create_db_engine(f"sqlite:///{db_path}")
    init_db(eng)
    return eng


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app(engine=engine)
    with TestClient(app) as c:
        yield c
