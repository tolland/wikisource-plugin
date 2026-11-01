import base64
from pathlib import Path

from fastapi.testclient import TestClient

from ide_test_support.__main__ import seed_browser
from wtbot.db import create_db_engine
from wtbot.main import create_app


def test_database_identity_survives_restart_and_rejects_foreign_save(
    tmp_path: Path,
) -> None:
    path = "/ide/en/Index/IDE integration.djvu/@wikitext"
    identities: list[str] = []
    for name in ("first", "second"):
        database = tmp_path / name / "wtbot.db"
        seed_browser(database)
        engine = create_db_engine(f"sqlite:///{database}")
        try:
            app = create_app(engine=engine, blob_root=tmp_path / name / "blobs")
            with TestClient(app) as client:
                content = client.get("/vfs/content", params={"path": path}).json()
                identity = content["database_id"]
                assert identity
                identities.append(identity)
                stat = client.get("/vfs/stat", params={"path": path}).json()
                assert stat["database_id"] == identity
                if name == "second":
                    rejected = client.post(
                        "/vfs/content",
                        json={
                            "path": path,
                            "content_base64": base64.b64encode(b"Stale text").decode(),
                            "base_revid": content["revid"],
                            "database_id": identities[0],
                        },
                    )
                    assert rejected.status_code == 409
                    assert rejected.json()["code"] == "database-changed"
                    assert (
                        client.get("/vfs/content", params={"path": path}).json()
                        == content
                    )
            with TestClient(
                create_app(engine=engine, blob_root=tmp_path / name / "blobs")
            ) as client:
                assert (
                    client.get("/vfs/content", params={"path": path}).json()[
                        "database_id"
                    ]
                    == identity
                )
        finally:
            engine.dispose()
    assert identities[0] != identities[1]
