"""How a fetched page is handled, decided from its content_model.

We trust the remote's ``content_model`` rather than parsing titles by hand --
an Index reports ``proofread-index``, a Page reports ``proofread-page``. The one
structural override is the **File namespace**: a File's content_model is plain
``wikitext`` (its description page), but the payload we actually want is the
binary scan, so the namespace decides before content_model does.
"""

from enum import Enum

from wtbot.model import NsRole, role_for_canonical
from wtbot.wiki.wiki_types import RemotePage


class Handling(str, Enum):
    file = "file"  # download the binary; the wikitext is just a description
    proofread_index = "proofread_index"  # parse pagelist, find File, fan out Pages
    proofread_page = "proofread_page"  # transcription + pagequality
    wikitext = "wikitext"  # plain page (mainspace, Book, Author, ...)
    unknown = "unknown"


_MODEL_TO_HANDLING = {
    "proofread-index": Handling.proofread_index,
    "proofread-page": Handling.proofread_page,
    "wikitext": Handling.wikitext,
}


def classify(content_model: str, namespace_role: NsRole | None = None) -> Handling:
    if namespace_role is NsRole.file:
        return Handling.file
    return _MODEL_TO_HANDLING.get(content_model, Handling.unknown)


def classify_remote(page: RemotePage) -> Handling:
    role = role_for_canonical(page.namespace_canonical or "")
    return classify(page.content_model, role)
