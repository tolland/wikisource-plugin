"""Populate the Namespace table from a live pywikibot Site object."""

from sqlmodel import Session, select

from wtbot.model import Namespace, Site
from wtbot.model.namespace import role_for_canonical


def sync_namespaces(session: Session, site: Site, namespaces) -> None:
    """Upsert all namespaces from a pywikibot NamespacesDict into the DB.

    Safe to call repeatedly — existing rows are updated in place.
    ``namespaces`` is a ``pywikibot.site._namespace.NamespacesDict``.
    """
    for ns in namespaces.values():
        key = ns.id
        canonical = ns.canonical_name or ""
        local = ns.custom_name or canonical

        existing = session.exec(
            select(Namespace).where(Namespace.site_pk == site.pk, Namespace.key == key)
        ).first()

        row = existing or Namespace(site_pk=site.pk, key=key)
        row.canonical_name = canonical
        row.local_name = local
        row.role = role_for_canonical(canonical)
        row.subpages = bool(getattr(ns, "subpages", False))
        row.content = bool(getattr(ns, "content", False))
        row.case = getattr(ns, "case", None)
        session.add(row)

    session.commit()
