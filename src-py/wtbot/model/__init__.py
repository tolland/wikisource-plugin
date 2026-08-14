"""Single source of truth for the wtbot data model.

These SQLModel classes define the SQLite schema shared by the IntelliJ plugin
(via JDBC) and the pywikibot worker. The former hand-written
``schema/schema.sql`` was removed so the model has one authority -- these
classes. See ``src-py/DESIGN.md`` for the rationale behind each table.
"""

from wtbot.model.annotation.box_range_link import BoxRangeLink
from wtbot.model.annotation.scan_annotation import AnnotationCategory, ScanAnnotation
from wtbot.model.annotation.text_target_anchor import TextTargetAnchor
from wtbot.model.commit import Commit, CommitStatus
from wtbot.model.edit_journal import EditJournal
from wtbot.model.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.model.file_blob import FileBlob
from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind
from wtbot.model.sync.index_link import IndexLink
from wtbot.model.sync.page_link import PageLink
from wtbot.model.sync.promotion import (
    BatchStatus,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
)
from wtbot.model.sync.remote_link import LinkOrigin, RevisionLink
from wtbot.model.wiki.content import Content
from wtbot.model.wiki.namespace import Namespace, NsRole, role_for_canonical
from wtbot.model.wiki.page import FetchState, Page
from wtbot.model.wiki.revision import Revision
from wtbot.model.wiki.site import Site
from wtbot.model.wiki.site_credential import SiteCredential
from wtbot.model.wiki.slot import MAIN_SLOT, Slot
from wtbot.model.wiki.transclusion import Transclusion
from wtbot.model.wikisource.file_meta import FileMeta, FileOrigin
from wtbot.model.wikisource.index_meta import IndexMeta
from wtbot.model.wikisource.page_meta import (
    PageMeta,
    default_short_name,
)

__all__ = [
    "AnnotationCategory",
    "ScanAnnotation",
    "TextTargetAnchor",
    "BoxRangeLink",
    "OcrBackendConfig",
    "OcrBackendKind",
    "Site",
    "Namespace",
    "NsRole",
    "role_for_canonical",
    "Page",
    "FetchState",
    "Revision",
    "BatchStatus",
    "Promotion",
    "PromotionBatch",
    "PromotionIntent",
    "PromotionStatus",
    "RevisionLink",
    "PageLink",
    "LinkOrigin",
    "Slot",
    "MAIN_SLOT",
    "Content",
    "IndexLink",
    "IndexMeta",
    "PageMeta",
    "FileMeta",
    "FileOrigin",
    "default_short_name",
    "FileBlob",
    "Transclusion",
    "FetchRequest",
    "FetchKind",
    "FetchStatus",
    "EditJournal",
    "Commit",
    "CommitStatus",
    "SiteCredential",
]
