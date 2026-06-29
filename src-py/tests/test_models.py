"""Exercise the model graph end to end: a Site with a Page, a fanned-out
FetchRequest tree, a journal entry and a commit. Mostly this proves the schema
(FKs, self-reference, enums) builds and round-trips."""

from sqlmodel import select

from wtbot.sqlmodel import (
    Commit,
    EditJournal,
    FetchKind,
    FetchRequest,
    Namespace,
    NsRole,
    Page,
    Site,
    role_for_canonical,
)


def test_role_resolution_is_id_independent():
    # Same canonical name -> same role regardless of the numeric key.
    assert role_for_canonical("Index") is NsRole.index
    assert role_for_canonical("Page") is NsRole.page
    assert role_for_canonical("Wibble") is NsRole.other


def test_per_site_namespace_map(session):
    site = Site(family="wikisource", code="en", articlepath="/wiki/$1")
    session.add(site)
    session.commit()
    # en.wikisource uses 106 for Index; a fresh ProofreadPage install uses 252.
    ns = Namespace(
        site_pk=site.pk, key=106, canonical_name="Index", local_name="Index",
        role=role_for_canonical("Index"),
    )
    session.add(ns)
    session.commit()
    got = session.exec(select(Namespace).where(Namespace.role == NsRole.index)).one()
    assert got.key == 106


def test_index_fanout_and_journal(session):
    site = Site(family="mywikisource", code="en", articlepath="/wiki/$1")
    session.add(site)
    session.commit()

    index = Page(
        site_pk=site.pk,
        title="Index:Tractatus.djvu",
        namespace_role=NsRole.index,
        page_count=2,
    )
    session.add(index)
    session.commit()

    parent = FetchRequest(site_pk=site.pk, title=index.title, kind=FetchKind.index)
    session.add(parent)
    session.commit()
    child = FetchRequest(
        site_pk=site.pk,
        parent_pk=parent.pk,
        title="Page:Tractatus.djvu/1",
        kind=FetchKind.page,
    )
    session.add(child)
    session.commit()
    assert child.parent_pk == parent.pk

    # An IDE save: journal row + dirty flag, distinct from any remote state.
    index.dirty = True
    session.add(EditJournal(page_pk=index.pk, body="== edited ==", base_revid=None))
    session.add(index)
    session.commit()
    j = session.exec(select(EditJournal).where(EditJournal.page_pk == index.pk)).one()
    assert j.committed is False

    # An outbound push attempt.
    session.add(Commit(page_pk=index.pk, base_revid=1, submitted_body="== edited =="))
    session.commit()
    c = session.exec(select(Commit)).one()
    assert c.status.value == "pending"
