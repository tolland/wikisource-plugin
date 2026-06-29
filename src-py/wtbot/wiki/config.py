"""Programmatic pywikibot configuration.

pywikibot's tutorial flow wants a hand-written ``user-config.py`` and family
files. That doesn't suit a backend that must be driven from tests, a Typer CLI,
and an IntelliJ-launched process. Instead we configure pywikibot entirely from a
``WikiSettings`` object: no ``user-config.py`` on disk, an ephemeral
``PYWIKIBOT_DIR``, and ``Site(url=...)`` (AutoFamily) so no family file is needed.

Must run before the first ``import pywikibot`` triggers config loading, which is
why the pywikibot import lives inside this function and inside the client, never
at module import time.
"""

from __future__ import annotations

import os
import tempfile

from wtbot.settings import WikiSettings


def configure_pywikibot(settings: WikiSettings) -> str:
    """Apply settings to pywikibot's global config. Returns the config dir used."""
    # No user-config.py; run anonymously unless a username is supplied below.
    os.environ.setdefault("PYWIKIBOT_NO_USER_CONFIG", "1")

    if settings.ca_bundle:
        # pywikibot uses requests under the hood; this is how you trust a
        # self-signed cert on a local .lan wiki without disabling verification.
        os.environ["REQUESTS_CA_BUNDLE"] = settings.ca_bundle

    config_dir = settings.config_dir or tempfile.mkdtemp(prefix="wtbot-pwb-")
    os.environ["PYWIKIBOT_DIR"] = config_dir

    import pywikibot.config as pwbconfig

    pwbconfig.base_dir = config_dir
    pwbconfig.put_throttle = 1  # be polite; tune per deployment

    if settings.username:
        fam = pwbconfig.usernames.get(settings.family)
        if fam is None:
            pwbconfig.usernames[settings.family] = fam = {}
        fam[settings.code] = settings.username

    return config_dir
