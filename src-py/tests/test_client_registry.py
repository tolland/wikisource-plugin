"""Client reuse.

Building a client is several upstream requests (site detection, then login), so
"one client per fetch request" was most of our rate-limit spend on a large
Index fan-out. These tests pin the reuse and, just as importantly, pin where it
must *not* happen: a changed credential has to build a new client rather than
keep using a session authenticated as somebody else.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from wtbot.model import Site
from wtbot.settings import WikiSettings
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.client_registry import ClientKey, ClientRegistry, make_client_factory


def _site(pk: int = 1) -> Site:
    return Site(
        pk=pk,
        family="wikisource",
        code="en",
        api_url="https://en.wikisource.org/w/api.php",
    )


def _settings(**overrides) -> WikiSettings:
    base = dict(
        family="wikisource",
        code="en",
        api_url="https://en.wikisource.org/w/api.php",
    )
    base.update(overrides)
    return WikiSettings(**base)


class _CountingBuilder:
    def __init__(self):
        self.calls: list[WikiSettings] = []

    def __call__(self, settings: WikiSettings) -> FakeWikiClient:
        self.calls.append(settings)
        return FakeWikiClient()


def test_same_site_reuses_one_client():
    builder = _CountingBuilder()
    registry = ClientRegistry(builder=builder)
    site = _site()

    clients = [registry.get(site, _settings()) for _ in range(200)]

    assert len(builder.calls) == 1, "one client per site, not one per request"
    assert all(c is clients[0] for c in clients)


def test_concurrent_requests_do_not_build_duplicate_clients():
    """pywikibot client construction mutates process-global state, so two
    requests missing the cache together must not construct in parallel."""
    calls = 0
    calls_lock = threading.Lock()
    workers = 12
    start = threading.Barrier(workers)

    def builder(settings: WikiSettings) -> FakeWikiClient:
        nonlocal calls
        with calls_lock:
            calls += 1
        # Keep the first build open long enough for every worker to observe
        # the original race if construction is outside the registry lock.
        time.sleep(0.05)
        return FakeWikiClient()

    registry = ClientRegistry(builder=builder)
    site = _site()

    def get_client() -> FakeWikiClient:
        start.wait()
        return registry.get(site, _settings())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        clients = list(pool.map(lambda _: get_client(), range(workers)))

    assert calls == 1
    assert all(client is clients[0] for client in clients)


def test_distinct_sites_get_distinct_clients():
    builder = _CountingBuilder()
    registry = ClientRegistry(builder=builder)

    first = registry.get(_site(1), _settings())
    second = registry.get(
        _site(2), _settings(api_url="https://wikisource.lan/w/api.php")
    )

    assert first is not second
    assert len(builder.calls) == 2


def test_changed_credentials_build_a_new_client():
    builder = _CountingBuilder()
    registry = ClientRegistry(builder=builder)
    site = _site()

    anonymous = registry.get(site, _settings())
    logged_in = registry.get(site, _settings(username="Admin", password="pw1"))
    rotated = registry.get(site, _settings(username="Admin", password="pw2"))

    assert anonymous is not logged_in
    assert logged_in is not rotated
    assert len(builder.calls) == 3


def test_client_key_never_holds_the_password():
    key = ClientKey.of(_site(), _settings(username="Admin", password="hunter2"))
    assert "hunter2" not in repr(key)
    assert key.secret_digest != ""


def test_invalidate_drops_cached_clients():
    builder = _CountingBuilder()
    registry = ClientRegistry(builder=builder)

    registry.get(_site(1), _settings())
    registry.get(_site(2), _settings(api_url="https://other.lan/w/api.php"))
    assert len(registry) == 2

    assert registry.invalidate(site_pk=1) == 1
    assert len(registry) == 1

    registry.get(_site(1), _settings())
    assert len(builder.calls) == 3  # site 1 was rebuilt after invalidation


def test_factory_resolves_settings_per_call_but_reuses_the_client():
    """A credential written while the process runs must take effect: the
    resolver runs every time, and only an unchanged result reuses the client."""
    builder = _CountingBuilder()
    credentials: dict[str, str | None] = {"username": None, "password": None}

    def resolver(site: Site) -> WikiSettings:
        return _settings(**credentials)

    factory = make_client_factory(resolver, registry=ClientRegistry(builder=builder))
    site = _site()

    factory(site)
    factory(site)
    assert len(builder.calls) == 1

    credentials.update(username="Admin", password="secret")
    factory(site)
    assert len(builder.calls) == 2
    assert builder.calls[-1].username == "Admin"


def test_worker_run_builds_one_client_for_a_whole_fan_out(engine):
    """End to end through the fetch worker: N queued requests, one client."""
    from sqlmodel import Session

    from wtbot.model import FetchKind, FetchRequest
    from wtbot.wiki.wiki_types import RemotePage
    from wtbot.worker import run_pending

    builder = _CountingBuilder()
    titles = [f"Page:Book.djvu/{n}" for n in range(1, 26)]
    pages = {
        title: RemotePage(
            title=title,
            namespace_key=104,
            namespace_canonical="Page",
            content_model="proofread-page",
            text="body",
            revid=1,
        )
        for title in titles
    }

    def building_fake(settings: WikiSettings) -> FakeWikiClient:
        builder.calls.append(settings)
        return FakeWikiClient(pages=pages)

    with Session(engine) as session:
        site = Site(family="wikisource", code="en")
        session.add(site)
        session.commit()
        session.refresh(site)
        for title in titles:
            session.add(FetchRequest(site_pk=site.pk, title=title, kind=FetchKind.page))
        session.commit()

        factory = make_client_factory(
            lambda s: _settings(), registry=ClientRegistry(builder=building_fake)
        )
        handled = run_pending(session, factory, limit=100)

    assert handled == len(titles)
    assert len(builder.calls) == 1
