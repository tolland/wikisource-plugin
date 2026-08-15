import hashlib
import logging
import threading
from dataclasses import dataclass

from wtbot.model import Site
from wtbot.settings import WikiSettings
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.rate_limits import RateLimitPolicy

"""Process-wide reuse of wiki clients.

Building a ``PywikibotClient`` is not cheap and is not local. Because we
construct sites from a URL, pywikibot uses an ``AutoFamily``, and it re-detects
the site over HTTP; then, if credentials are configured, we log in. So a client
built per fetch request costs several upstream requests before the one the
caller wanted -- and does it again for the next page of the same book.

That was the actual shape of the reliability problem this module exists to fix.
Fanning an Index out into hundreds of Page: children multiplied a per-page cost
of one or two requests into seven or eight, most of them site detection and
login, which is exactly how a 200 req/min allowance is exhausted. The
rate-limit response then arrives as an HTML page where JSON was expected, and
pywikibot reports it as ``SiteDefinitionError: Invalid AutoFamily(...)`` --
error text that describes our configuration rather than the throttling that
caused it.

Clients are therefore cached per site *and per credential*: a changed password
or a switch between anonymous and authenticated access must build a new client
rather than silently keep using the old session.
"""

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientKey:
    """Identity of a client. Two requests share a client iff they agree on
    every field -- endpoint and credentials both."""

    site_pk: int | None
    family: str
    code: str
    api_url: str | None
    username: str | None
    bot_name: str | None
    secret_digest: str  # never the password itself, only a change detector
    rate_limits: RateLimitPolicy

    @classmethod
    def of(cls, site: Site, settings: WikiSettings) -> "ClientKey":
        return cls(
            site_pk=site.pk,
            family=settings.family,
            code=settings.code,
            api_url=settings.api_url,
            username=settings.username,
            bot_name=settings.bot_name,
            secret_digest=_digest(settings.password),
            rate_limits=settings.rate_limits,
        )


def _digest(secret: str | None) -> str:
    if secret is None:
        return ""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


class ClientRegistry:
    """Thread-safe cache of live clients, keyed by ClientKey."""

    def __init__(self, builder=None) -> None:
        # None rather than a default of ``get_wiki_client``: a default argument
        # binds the function object once, at import, which would make the
        # module attribute unpatchable for tests. Resolved per build instead.
        self._builder = builder
        self._clients: dict[ClientKey, WikiClient] = {}
        self._lock = threading.Lock()

    def _build(self, settings: WikiSettings) -> WikiClient:
        builder = self._builder or get_wiki_client
        return builder(settings)

    def get(self, site: Site, settings: WikiSettings) -> WikiClient:
        key = ClientKey.of(site, settings)
        with self._lock:
            client = self._clients.get(key)
            if client is not None:
                return client

            # Client construction mutates pywikibot's process-global config,
            # family registry and Site cache.  It must be serialized even for
            # different keys; allowing duplicate concurrent builds can corrupt
            # one build with another site's state.  Construction is rare and
            # every cached lookup above remains a short critical section.
            client = self._build(settings)
            self._clients[key] = client
        log.info(
            "built wiki client for %s:%s (%s) as %s",
            settings.family,
            settings.code,
            settings.api_url or "family file",
            settings.username or "anonymous",
        )
        return client

    def invalidate(self, site_pk: int | None = None) -> int:
        """Drop cached clients -- all of them, or one site's. Returns how many
        were dropped. Needed when credentials change under a running process."""
        with self._lock:
            keys = [
                key
                for key in self._clients
                if site_pk is None or key.site_pk == site_pk
            ]
            for key in keys:
                del self._clients[key]
        return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._clients)


def make_client_factory(settings_for_site, *, registry: ClientRegistry | None = None):
    """Wrap a ``Site -> WikiSettings`` resolver into a memoizing ClientFactory.

    The resolver still runs per call, so a credential written to the DB while
    the process is running is picked up: it changes the key, which builds a new
    client instead of reusing the anonymous one.
    """
    # `registry or ClientRegistry()` would be wrong: __len__ makes an empty
    # registry falsy, so an injected one would be silently replaced by a real
    # one -- and a test that meant to inject a fake would go to the network.
    if registry is None:
        registry = ClientRegistry()

    def factory(site: Site) -> WikiClient:
        return registry.get(site, settings_for_site(site))

    factory.registry = registry  # exposed for invalidation and for tests
    return factory
