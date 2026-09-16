import json
import sqlite3
from io import BytesIO

import pytest
from PIL import Image

from wtbot.annotation_normalization import backfill


@pytest.fixture
def legacy(tmp_path):
    database = tmp_path / "legacy.db"
    box = dict(pk=1, page_pk=10, annotation_id="box", x=20, y=60, width=100, height=120)
    dump = tmp_path / "out.json"
    dump.write_text(json.dumps([box]))
    with sqlite3.connect(database) as db:
        db.executescript("""
            CREATE TABLE scanannotation (
                pk INTEGER PRIMARY KEY, page_pk INTEGER, annotation_id TEXT,
                x REAL, y REAL, width REAL, height REAL,
                normalized_x REAL, normalized_y REAL, normalized_width REAL, normalized_height REAL);
            INSERT INTO scanannotation VALUES (1,10,'box',20,60,100,120,NULL,NULL,NULL,NULL);
            CREATE TABLE proofreadpagemeta (page_pk INTEGER PRIMARY KEY, source_image_url TEXT, thumb_url TEXT);
            INSERT INTO proofreadpagemeta VALUES (10,'https://example.test/page.jpg',NULL);
        """)
    buffer = BytesIO()
    Image.new("RGB", (200, 600)).save(buffer, format="PNG")
    return database, dump, buffer.getvalue()


def test_backfill_dry_run_apply_and_repeat(legacy, monkeypatch):
    database, dump, image = legacy
    monkeypatch.setattr(
        "wtbot.annotation_normalization.fetch_image_bytes", lambda url: image
    )
    count, images = backfill(database, dump)
    assert count == 1
    assert (images[0].width, images[0].height) == (200, 600)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT normalized_x FROM scanannotation").fetchone() == (
            None,
        )
    for _ in range(2):
        backfill(database, dump, apply=True)
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT normalized_x, normalized_y, normalized_width, normalized_height FROM scanannotation"
        ).fetchone() == (0.1, 0.1, 0.5, 0.2)
        assert db.execute("SELECT x,y,width,height FROM scanannotation").fetchone() == (
            20,
            60,
            100,
            120,
        )


def test_cached_bytes_win_over_changed_remote_image(legacy, tmp_path, monkeypatch):
    database, dump, image = legacy
    cache = tmp_path / "page_images"
    cache.mkdir()
    (cache / "10-src.jpg").write_bytes(image)

    def unexpected(url):
        pytest.fail("should use cached bytes")

    monkeypatch.setattr("wtbot.annotation_normalization.fetch_image_bytes", unexpected)
    _, images = backfill(database, dump, blob_root=tmp_path, apply=True)
    assert images[0].location == str(cache / "10-src.jpg")


def test_changed_rows_refused(legacy):
    database, dump, _ = legacy
    with sqlite3.connect(database) as db:
        db.execute("UPDATE scanannotation SET x=21")
    with pytest.raises(ValueError, match="differs"):
        backfill(database, dump, apply=True)


def test_bad_image_geometry_leaves_all_rows_untouched(legacy, monkeypatch):
    database, dump, _ = legacy
    buffer = BytesIO()
    Image.new("RGB", (20, 20)).save(buffer, format="PNG")
    monkeypatch.setattr(
        "wtbot.annotation_normalization.fetch_image_bytes",
        lambda url: buffer.getvalue(),
    )
    with pytest.raises(ValueError, match="does not fit"):
        backfill(database, dump, apply=True)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT normalized_x FROM scanannotation").fetchone() == (
            None,
        )
