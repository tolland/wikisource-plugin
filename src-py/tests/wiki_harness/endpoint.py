from dataclasses import dataclass

"""Connection details for one running MediaWiki instance in the test harness."""


@dataclass(frozen=True)
class WikiEndpoint:
    """Where a harness wiki lives and how to authenticate against it.

    Deliberately separate from the compose plumbing in ``stack.py`` so tests
    that talk to an already-running wiki (``--reuse-wikisource``) need nothing
    from docker.
    """

    role: str  # 'upstream' | 'local' -- also the compose service discriminator
    base_url: str
    api_url: str
    username: str
    password: str

    def page_url(self, title: str) -> str:
        return f"{self.base_url}/index.php?title={title.replace(' ', '_')}"
