"""One-off, offline backfill between the two normalized-annotation migrations.

The dump and database must describe the same rows. Image dimensions come from
cached bytes when available, otherwise the stored reference URL. URL downloads
assume the reference rendering has not changed since the boxes were drawn.
"""

import argparse
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, TypeAdapter

from wtbot.api.reference_image import fetch_image_bytes


class LegacyAnnotation(BaseModel):
    pk: int
    title_pk: int
    annotation_id: str
    x: float
    y: float
    width: float
    height: float

    def pixels(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.width, self.height


@dataclass(frozen=True)
class ImageDimensions:
    title_pk: int
    width: int
    height: int
    sha256: str
    location: str


@dataclass(frozen=True)
class ConvertedAnnotation:
    legacy: LegacyAnnotation
    geometry: tuple[float, float, float, float]


def normalize_box(
    box: LegacyAnnotation, width: int, height: int
) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    x, y, w, h = (box.x / width, box.y / height, box.width / width, box.height / height)
    if (
        not all(math.isfinite(v) for v in (x, y, w, h))
        or min(x, y) < 0
        or min(w, h) <= 0
        or x + w > 1 + 1e-9
        or y + h > 1 + 1e-9
    ):
        raise ValueError(f"annotation {box.pk} does not fit image {width}x{height}")
    return x, y, w, h


def _check_row(connection: sqlite3.Connection, box: LegacyAnnotation) -> None:
    row = connection.execute(
        "SELECT title_pk, annotation_id, x, y, width, height FROM scanannotation WHERE pk=?",
        (box.pk,),
    ).fetchone()
    if row != (box.title_pk, box.annotation_id, *box.pixels()):
        raise ValueError(f"annotation {box.pk} is missing or differs from the dump")


def backfill(
    database: Path,
    dump: Path,
    *,
    blob_root: Path | None = None,
    apply: bool = False,
) -> tuple[int, list[ImageDimensions]]:
    boxes = TypeAdapter(list[LegacyAnnotation]).validate_json(dump.read_bytes())
    if len({box.pk for box in boxes}) != len(boxes):
        raise ValueError("duplicate annotation primary keys in dump")
    dimensions: dict[int, ImageDimensions] = {}
    converted: list[ConvertedAnnotation] = []
    # mode=rw avoids accidentally creating a database when its path is wrong.
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=rw", uri=True)
    try:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(scanannotation)")
        }
        if (
            not {
                "x",
                "normalized_x",
                "normalized_y",
                "normalized_width",
                "normalized_height",
            }
            <= columns
        ):
            raise ValueError("database must be at migration a21d6430c901")
        for box in boxes:
            _check_row(connection, box)
            if box.title_pk not in dimensions:
                row = connection.execute(
                    "SELECT source_image_url, thumb_url FROM proofreadpagemeta WHERE title_pk=?",
                    (box.title_pk,),
                ).fetchone()
                url = (row[0] or row[1]) if row else None
                if not url:
                    raise ValueError(f"page {box.title_pk} has no reference image URL")
                ext = Path(url.split("?", 1)[0]).suffix or ".jpg"
                cache = (
                    blob_root / "page_images" / f"{box.title_pk}-src{ext}"
                    if blob_root
                    else None
                )
                if cache is not None and cache.is_file():
                    data, location = cache.read_bytes(), str(cache)
                else:
                    data, location = fetch_image_bytes(url), url
                with Image.open(BytesIO(data)) as image:
                    width, height = image.size
                dimensions[box.title_pk] = ImageDimensions(
                    box.title_pk,
                    width,
                    height,
                    hashlib.sha256(data).hexdigest(),
                    location,
                )
            image = dimensions[box.title_pk]
            converted.append(
                ConvertedAnnotation(box, normalize_box(box, image.width, image.height))
            )
        if apply:
            # No network inside the transaction. Check again before writing so
            # a concurrent edit cannot be overwritten using stale dump geometry.
            connection.execute("BEGIN IMMEDIATE")
            for item in converted:
                _check_row(connection, item.legacy)
                connection.execute(
                    "UPDATE scanannotation SET normalized_x=?, normalized_y=?, "
                    "normalized_width=?, normalized_height=? WHERE pk=?",
                    (*item.geometry, item.legacy.pk),
                )
            connection.commit()
        return len(converted), list(dimensions.values())
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--blob-root", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write normalized values (default: dry run)",
    )
    args = parser.parse_args()
    count, images = backfill(
        args.database, args.dump, blob_root=args.blob_root, apply=args.apply
    )
    print(
        json.dumps(
            {
                "applied": args.apply,
                "annotations": count,
                "images": [asdict(i) for i in images],
            },
            indent=2,
        )
    )
