import tempfile
from dataclasses import dataclass

from wiki_harness.endpoint import WikiEndpoint
from wtbot.settings import WikiSettings
from wtbot.wiki.client import PywikibotClient

"""pywikibot bound to a harness wiki.

The production fetch path is pywikibot, so anything asserted about revisions
should be assertable through the same library the worker uses -- otherwise the
harness proves something about ``requests`` rather than about wtbot.

``WikiSettings(api_url=...)`` drives ``Site(url=..., fam=...)``/AutoFamily, so
no family file is needed for an arbitrary docker host.  The family name must be
unique per harness endpoint because pywikibot's process-global Site cache does
not include the URL/port in its key. ``configure_pywikibot`` also mutates
process-global pywikibot config, so these fixtures are session-scoped and each
gets its own ephemeral ``PYWIKIBOT_DIR``.
"""


@dataclass(frozen=True)
class PwbHarness:
    """A configured pywikibot client plus the endpoint it points at."""

    endpoint: WikiEndpoint
    client: PywikibotClient

    @property
    def site(self):
        return self.client.site

    def page(self, title: str):
        import pywikibot

        return pywikibot.Page(self.site, title)

    def proofread_page(self, title: str):
        from pywikibot.proofreadpage import ProofreadPage

        return ProofreadPage(self.site, title)

    def main_slot_text(self, title: str) -> str:
        """The main slot's served content for the page's current revision.

        This is the ``text/x-wiki`` serialization -- for ``proofread-page`` it
        is the stored content *plus* the reconstructed ``<noinclude>`` header
        and footer wrappers, which is why its hash need not equal
        ``content_sha1``.
        """
        return self.page(title).latest_revision["slots"]["main"]["*"]


def pywikibot_harness(
    endpoint: WikiEndpoint, *, config_dir: str | None = None
) -> PwbHarness:
    settings = WikiSettings(
        # Both wikis use 127.0.0.1 and differ only by port.  A role-specific
        # AutoFamily name keeps their process-global pywikibot Site cache keys
        # distinct.
        family=f"harness-{endpoint.role}",
        code="en",
        api_url=endpoint.api_url,
        username=endpoint.username,
        password=endpoint.password,
        config_dir=config_dir or tempfile.mkdtemp(prefix="wtbot-harness-pwb-"),
    )
    return PwbHarness(endpoint=endpoint, client=PywikibotClient(settings))
