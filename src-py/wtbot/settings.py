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
    # Plain account password, or the bot password half of a BotPassword when
    # bot_name is also set. Never persisted -- sourced from process env only,
    # since Site rows (SQLite) deliberately carry no credentials.
    password: str | None = None
    bot_name: str | None = None  # BotPasswords "username@bot_name" suffix
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
            password=e.get("WTBOT_WIKI_PASSWORD") or None,
            bot_name=e.get("WTBOT_WIKI_BOTNAME") or None,
            ca_bundle=e.get("WTBOT_WIKI_CA_BUNDLE") or None,
            config_dir=e.get("WTBOT_PWB_DIR") or None,
        )

    @classmethod
    def from_site(cls, site, **overrides) -> "WikiSettings":
        """Build from a persisted Site row plus explicit credential overrides.

        Credentials (username/password/bot_name) are NOT sourced from env here:
        the production factory looks them up from the SiteCredential DB table and
        passes them as *overrides*, keeping each site's credentials independent.
        Non-credential process-env settings (ca_bundle, config_dir) still come
        from env since those are global/infrastructure, not per-site secrets."""
        env = cls.from_env()
        base = dict(
            family=site.family,
            code=site.code,
            api_url=site.api_url,
            # No credential fallback to env -- callers pass them as overrides
            ca_bundle=env.ca_bundle,
            config_dir=env.config_dir,
        )
        base.update(overrides)
        return cls(**base)
