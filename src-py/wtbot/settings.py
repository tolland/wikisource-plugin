from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WikiSettings:
    """Everything needed to reach one wiki, decoupled from how pywikibot wants it
    configured. This is the single injection point: tests build it inline, the
    Typer CLI builds it from flags/env, and an IntelliJ-launched process builds
    it from env or from a Site row. Reads are anonymous; ``username`` is only
    needed for write-back (commits)."""

    family: str
    code: str
    api_url: str | None = None  # full action API endpoint; preferred over family files
    username: str | None = None
    ca_bundle: str | None = None  # CA cert for a self-signed local wiki (.lan)
    config_dir: str | None = None  # PYWIKIBOT_DIR; ephemeral temp dir if None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "WikiSettings":
        e = env if env is not None else os.environ
        return cls(
            family=e.get("WTBOT_WIKI_FAMILY", "wikisource"),
            code=e.get("WTBOT_WIKI_CODE", "en"),
            api_url=e.get("WTBOT_WIKI_API_URL") or None,
            username=e.get("WTBOT_WIKI_USERNAME") or None,
            ca_bundle=e.get("WTBOT_WIKI_CA_BUNDLE") or None,
            config_dir=e.get("WTBOT_PWB_DIR") or None,
        )

    @classmethod
    def from_site(cls, site, **overrides) -> "WikiSettings":
        """Build from a persisted Site row, with optional auth/TLS overrides."""
        base = dict(
            family=site.family,
            code=site.code,
            api_url=site.api_url,
        )
        base.update(overrides)
        return cls(**base)
