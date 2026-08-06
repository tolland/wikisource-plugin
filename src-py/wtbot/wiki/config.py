import os
import stat
import tempfile
from pathlib import Path

from wtbot.settings import WikiSettings

"""Programmatic pywikibot configuration.

pywikibot's tutorial flow wants a hand-written ``user-config.py`` and family
files. That doesn't suit a backend that must be driven from tests, a Typer CLI,
and an IntelliJ-launched process. Instead we configure pywikibot entirely from a
``WikiSettings`` object: no ``user-config.py`` on disk, an ephemeral
``PYWIKIBOT_DIR``, and ``Site(url=..., fam=...)`` (AutoFamily) so no family file
is needed.

Must run before the first ``import pywikibot`` triggers config loading, which is
why the pywikibot import lives inside this function and inside the client, never
at module import time.

``write_password_entry`` is called AFTER the pywikibot Site object is
constructed, because AutoFamily derives its code from the endpoint at runtime
-- we can't know the complete 4-tuple discriminator before Site() runs.
"""

_PASSWORD_FILE = "user-password.cfg"


def configure_pywikibot(settings: WikiSettings) -> str:
    """Apply settings to pywikibot's global config. Returns the config dir used."""
    os.environ.setdefault("PYWIKIBOT_NO_USER_CONFIG", "1")

    if settings.ca_bundle:
        # pywikibot uses requests under the hood; this is how you trust a
        # self-signed cert on a local .lan wiki without disabling verification.
        os.environ["REQUESTS_CA_BUNDLE"] = settings.ca_bundle

    if settings.config_dir:
        Path(settings.config_dir).mkdir(parents=True, exist_ok=True)
        config_dir = settings.config_dir
    else:
        config_dir = tempfile.mkdtemp(prefix="wtbot-pwb-")
    os.environ["PYWIKIBOT_DIR"] = config_dir

    import pywikibot.config as pwbconfig

    pwbconfig.base_dir = config_dir

    # Retry policy (see WikiSettings): fail fast instead of pywikibot's
    # default 15 retries with exponential backoff. Every failure mode we have
    # actually hit -- missing token turning into rate limiting, a VCR cassette
    # rejecting an unrecorded request, a dead local service -- was a bug that
    # backoff only hid; a genuinely flaky link can raise these via env.
    pwbconfig.max_retries = settings.max_retries
    pwbconfig.retry_wait = settings.retry_wait

    if not hasattr(pwbconfig, "_wtbot_throttle_set"):
        pwbconfig.put_throttle = 1
        pwbconfig._wtbot_throttle_set = True

    # Throttle.checkMultiplicity() reads this file to detect concurrent bots.
    throttle_ctrl = Path(config_dir) / "throttle.ctrl"
    throttle_ctrl.touch(exist_ok=True)

    if settings.username:
        # Register under the explicit family/code AND the '*' wildcard.
        # AutoFamily sites (api_url) get the wildcard match; conventional sites
        # get the exact match.  write_password_entry() (called later, after the
        # Site object knows its runtime family/code) handles the password.
        for fam_key in (
            {settings.family, "*"} if settings.api_url else {settings.family}
        ):
            fam = pwbconfig.usernames.setdefault(fam_key, {})
            # pywikibot config is process-global, so a previous client/test may
            # already have populated this wildcard.  The current settings are
            # authoritative and must replace that stale username.
            fam["*"] = settings.username
            fam[settings.code] = settings.username

        # Point pywikibot at the password file even though it may be empty or
        # not yet exist -- write_password_entry appends to it after site creation.
        password_path = Path(config_dir) / _PASSWORD_FILE
        pwbconfig.password_file = str(password_path)

    _write_user_config(config_dir, settings)

    return config_dir


def write_password_entry(
    pwbconfig, *, code: str, family: str, settings: WikiSettings
) -> None:
    """Append a 4-tuple credential line to the password file.

    Uses the runtime ``code`` and ``family`` from the constructed pywikibot
    Site object so AutoFamily-derived names (e.g. 'wikisource-debian-13') are
    matched exactly. Multiple calls with different sites each add their own
    line; pywikibot iterates in reverse and matches the first exact hit."""
    if settings.bot_name:
        credential = f"BotPassword({settings.bot_name!r}, {settings.password!r})"
    else:
        credential = repr(settings.password)

    line = f"({code!r}, {family!r}, {settings.username!r}, {credential})\n"

    password_path = Path(pwbconfig.password_file)
    # Build a set of existing lines so we don't duplicate on reconnect.
    existing = password_path.read_text("utf-8") if password_path.exists() else ""
    if line in existing:
        return

    with password_path.open("a", encoding="utf-8") as f:
        f.write(line)
    password_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_user_config(config_dir: str, settings: WikiSettings) -> None:
    """Write a human-readable user-config.py in the pywikibot config dir.

    This file is NOT loaded by the running process (PYWIKIBOT_NO_USER_CONFIG=1
    stays set) but lets a developer cd into the temp dir and run pywikibot
    manually for debugging without having to reconstruct the config by hand."""
    lines = [
        "# Generated by wtbot -- for manual debugging only.",
        "# The running wtbot process does NOT load this file.",
        "# To use: cd to this directory, unset PYWIKIBOT_NO_USER_CONFIG, then",
        "#   python -m pywikibot login  (or run any pwb script).",
        "",
        f"family = {settings.family!r}",
        f"mylang = {settings.code!r}",
    ]
    if settings.api_url:
        lines.append(
            "# api_url = "
            f"{settings.api_url!r}  "
            f"(use Site(url=..., fam={settings.family!r}) in scripts)"
        )
    lines.append("")
    if settings.username:
        lines.append(f"usernames['*']['*'] = {settings.username!r}")
        lines.append(
            f"usernames[{settings.family!r}][{settings.code!r}] = {settings.username!r}"
        )
        lines.append(f"password_file = {_PASSWORD_FILE!r}")

    Path(config_dir, "user-config.py").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
