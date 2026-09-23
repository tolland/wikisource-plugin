import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from wtbot import main
from wtbot.db import create_db_engine


def test_import_does_not_open_default_database(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("WTBOT_DATABASE_URL", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", "import wtbot.main"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "database.db").exists()


def test_startup_initializes_only_the_supplied_engine(
    tmp_path: Path, monkeypatch
) -> None:
    default_path = tmp_path / "default.db"
    monkeypatch.setenv("WTBOT_DATABASE_URL", f"sqlite:///{default_path}")
    initialized: list[Engine] = []
    monkeypatch.setattr(main, "init_db", initialized.append)
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    try:
        app = main.create_app(engine=engine)
        assert initialized == []
        with TestClient(app):
            assert initialized == [engine]
        assert initialized == [engine]
        assert not default_path.exists()
    finally:
        engine.dispose()
