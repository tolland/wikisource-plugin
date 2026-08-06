import pytest
from sqlmodel import Session, select

from wtbot.model import (
    Commit,
    Content,
    EditJournal,
    FetchRequest,
    Namespace,
    Page,
    RemoteLink,
    Revision,
    Site,
    SiteCredential,
    Slot,
)
from wtbot.model.remote_link import LinkOrigin

"""Deleting a site through the API: previewed exactly, executed completely.

The delete-plan endpoint is the dry run -- `wtbot site delete` shows it instead
of deleting unless --force is given -- so the property that matters is that the
plan and the deletion are the same computation: what the plan names is exactly
what the DELETE removes, no more (the second site's rows, shared content) and
no less (every table that hangs off the site, including the self-referencing
fetch queue).
"""


@pytest.fixture
def seeded(engine):
    """Two sites holding the same title, entangled everywhere it matters.

    The doomed site gets a row in every site-scoped table; one Content row is
    shared with the survivor (it must outlive the deletion) and one is the
    doomed site's alone (it must not). A RemoteLink ties a revision of each
    site together, and the fetch queue has a parent/child pair to exercise the
    self-referencing foreign key.
    """
    with Session(engine) as s:
        doomed = Site(family="mywikisource", code="en", label="doomed")
        survivor = Site(family="wikisource", code="en", label="survivor")
        shared = Content(content_sha1="aaa", text="same bytes", size=10)
        private = Content(content_sha1="bbb", text="doomed bytes", size=12)
        s.add_all([doomed, survivor, shared, private])
        s.commit()

        doomed_page = Page(site_pk=doomed.pk, title="Page:Book.djvu/1")
        survivor_page = Page(site_pk=survivor.pk, title="Page:Book.djvu/1")
        s.add_all([doomed_page, survivor_page])
        s.commit()

        doomed_rev = Revision(page_pk=doomed_page.pk, revid=1)
        doomed_rev2 = Revision(page_pk=doomed_page.pk, revid=2)
        survivor_rev = Revision(page_pk=survivor_page.pk, revid=7)
        s.add_all([doomed_rev, doomed_rev2, survivor_rev])
        s.commit()

        parent = FetchRequest(site_pk=doomed.pk, title="Index:Book.djvu")
        s.add(parent)
        s.commit()

        s.add_all(
            [
                Slot(revision_pk=doomed_rev.pk, content_pk=shared.pk),
                Slot(revision_pk=doomed_rev2.pk, content_pk=private.pk),
                Slot(revision_pk=survivor_rev.pk, content_pk=shared.pk),
                RemoteLink(
                    local_revision_pk=doomed_rev.pk,
                    remote_revision_pk=survivor_rev.pk,
                    origin=LinkOrigin.manual,
                ),
                Namespace(
                    site_pk=doomed.pk, key=250, canonical_name="Page", local_name="Page"
                ),
                SiteCredential(site_pk=doomed.pk, username="Admin", password="pw"),
                FetchRequest(
                    site_pk=doomed.pk, parent_pk=parent.pk, title="Page:Book.djvu/1"
                ),
                EditJournal(page_pk=doomed_page.pk, body="draft"),
                Commit(page_pk=doomed_page.pk, submitted_body="pushed"),
            ]
        )
        s.commit()
        return {"doomed_pk": doomed.pk, "survivor_pk": survivor.pk}


def _rows(engine, model) -> list:
    with Session(engine) as s:
        return list(s.exec(select(model)).all())


def test_the_plan_names_every_table_and_deletes_nothing(client, engine, seeded):
    resp = client.get(f"/sites/{seeded['doomed_pk']}/delete-plan")

    assert resp.status_code == 200
    plan = resp.json()
    assert plan["label"] == "doomed"
    counted = {entry["table"]: entry["rows"] for entry in plan["counts"]}
    assert counted == {
        "remotelink": 1,
        "slot": 2,
        "content": 1,  # the private body only; the shared one is not orphaned
        "revision": 2,
        "editjournal": 1,
        "commit": 1,
        "fetchrequest": 2,  # parent and fan-out child both
        "page": 1,
        "namespace": 1,
        "sitecredential": 1,
        "site": 1,
    }

    # ...and asking was not acting.
    assert len(_rows(engine, Site)) == 2
    assert len(_rows(engine, Page)) == 2
    assert len(_rows(engine, Content)) == 2
    assert len(_rows(engine, FetchRequest)) == 2


def test_delete_removes_the_site_and_only_the_site(client, engine, seeded):
    resp = client.delete(f"/sites/{seeded['doomed_pk']}")

    assert resp.status_code == 200
    # The response is the same shape the plan previews, counted before the
    # rows went -- the receipt matches the estimate.
    counted = {entry["table"]: entry["rows"] for entry in resp.json()["counts"]}
    assert counted["site"] == 1
    assert counted["fetchrequest"] == 2

    assert [site.label for site in _rows(engine, Site)] == ["survivor"]
    survivor_pk = seeded["survivor_pk"]
    assert [p.site_pk for p in _rows(engine, Page)] == [survivor_pk]
    assert len(_rows(engine, Revision)) == 1
    assert len(_rows(engine, Slot)) == 1
    # The shared body survives -- the content store is cross-site by design --
    # while the body only the doomed site referenced is gone.
    assert [c.content_sha1 for c in _rows(engine, Content)] == ["aaa"]
    assert _rows(engine, RemoteLink) == []
    assert _rows(engine, FetchRequest) == []
    assert _rows(engine, Namespace) == []
    assert _rows(engine, SiteCredential) == []
    assert _rows(engine, EditJournal) == []
    assert _rows(engine, Commit) == []


def test_the_plan_is_the_deletion(client, seeded):
    """The preview and the delete must be the same computation."""
    planned = client.get(f"/sites/{seeded['doomed_pk']}/delete-plan").json()
    deleted = client.delete(f"/sites/{seeded['doomed_pk']}").json()
    assert planned == deleted


def test_deleting_an_unknown_site_404s(client):
    assert client.get("/sites/999/delete-plan").status_code == 404
    assert client.delete("/sites/999").status_code == 404
