from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class FileOrigin(str, Enum):
    remote = "remote"  # fetched from the wiki
    paste = "paste"  # screenshot pasted in the editor
    ocr = "ocr"  # produced by a templated-region OCR run


class FileMeta(SQLModel, table=True):
    """Provenance for File: pages.

    For images cropped out of a scan page, the crop geometry (in source
    raster pixels) records where the image came from — which is also exactly
    the input a templated-region batch OCR run iterates over, so it is
    captured from day one rather than reconstructed later.
    """

    __table_args__ = (UniqueConstraint("page_pk", name="uq_filemeta_page"),)

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    origin: FileOrigin = FileOrigin.remote
    source_page_pk: int | None = Field(default=None, foreign_key="page.pk")
    source_page_number: int | None = None
    crop_x: int | None = None
    crop_y: int | None = None
    crop_w: int | None = None
    crop_h: int | None = None
