from collections import defaultdict

import pytest

from wtbot.model import NsRole
from wtbot.settings import WikiSettings
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.dispatch import Handling, classify, classify_remote
from wtbot.wiki.rate_limits import TIER_LIMITS, RateLimitPolicy, RateLimitTier
from wtbot.wiki.wiki_types import PageNotFound, RemotePage


def _page(title, content_model, ns_canonical, ns_key, text="x"):
    return RemotePage(
        title=title,
        namespace_key=ns_key,
        namespace_canonical=ns_canonical,
        content_model=content_model,
        text=text,
        revid=1,
        sha1="deadbeef",
    )


class TestDispatch:
    def test_index_keys_on_content_model(self):
        assert classify("proofread-index") is Handling.proofread_index

    def test_page_keys_on_content_model(self):
        assert classify("proofread-page") is Handling.proofread_page

    def test_file_is_namespace_override_not_content_model(self):
        # A File reports content_model 'wikitext' but must be handled as a binary.
        assert classify("wikitext", NsRole.file) is Handling.file

    def test_plain_wikitext(self):
        assert classify("wikitext", NsRole.main) is Handling.wikitext

    def test_unknown_model(self):
        assert classify("flow-board") is Handling.unknown

    def test_classify_remote_resolves_role_from_canonical_name(self):
        # 'File' canonical name -> file handling regardless of content_model.
        fp = _page("File:Foo.djvu", "wikitext", "File", 6)
        assert classify_remote(fp) is Handling.file
        ip = _page("Index:Foo.djvu", "proofread-index", "Index", 252)
        assert classify_remote(ip) is Handling.proofread_index


class TestFakeClient:
    def test_get_page_roundtrip(self):
        p = _page("Index:Foo.djvu", "proofread-index", "Index", 252)
        client = FakeWikiClient(pages={p.title: p})
        assert client.get_page("Index:Foo.djvu").content_model == "proofread-index"

    def test_missing_page_raises(self):
        with pytest.raises(PageNotFound):
            FakeWikiClient().get_page("Index:Nope.djvu")

    def test_download_file_writes_bytes(self, tmp_path):
        client = FakeWikiClient(files={"File:Foo.djvu": b"DJVU-BYTES"})
        dest = tmp_path / "blobs" / "foo.djvu"
        out = client.download_file("File:Foo.djvu", dest)
        assert out.read_bytes() == b"DJVU-BYTES"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(PageNotFound):
            FakeWikiClient().download_file("File:Nope.djvu", tmp_path / "x")


class TestRateLimitPolicy:
    """The pacing policy, checked against the published tiers.

    Nothing reports which rate-limit bucket a request landed in, so these
    numbers are chosen rather than discovered. Checking them against the
    documented limits is the only feedback available short of being refused.
    """

    def test_the_default_fits_the_tier_it_targets(self):
        policy = RateLimitPolicy()
        assert policy.target_tier is RateLimitTier.authenticated_new
        assert policy.fits_tier()
        assert policy.reads_per_minute <= TIER_LIMITS[RateLimitTier.authenticated_new]

    def test_pywikibots_own_default_would_not_fit(self):
        """Why this exists: 0.1s is pywikibot's minthrottle default, and it is
        three times the allowance for the tier we are in."""
        assert not RateLimitPolicy(read_throttle=0.1).fits_tier()
        assert RateLimitPolicy(read_throttle=0.1).reads_per_minute == 600

    def test_the_default_would_fit_an_established_editor_easily(self):
        assert RateLimitPolicy().fits_tier(RateLimitTier.authenticated_established)

    def test_an_exempt_identity_has_no_ceiling_to_exceed(self):
        assert RateLimitPolicy(read_throttle=0.001).fits_tier(RateLimitTier.exempt)

    def test_slower_returns_a_new_policy_and_mutates_nothing(self):
        """A 429 calls for this, but applying it automatically would hide a
        wrong configuration behind a process that quietly re-paces itself."""
        policy = RateLimitPolicy()
        slower = policy.slower()
        assert slower.read_throttle == policy.read_throttle * 2
        assert policy.read_throttle == RateLimitPolicy().read_throttle

    def test_a_disabled_throttle_reports_an_infinite_rate_rather_than_dividing_by_zero(
        self,
    ):
        assert RateLimitPolicy(read_throttle=0).reads_per_minute == float("inf")
        assert not RateLimitPolicy(read_throttle=0).fits_tier()

    def test_the_user_agent_carries_contact_information(self):
        """Wikimedia's policy requires it, and a client without it is put in
        the 10 req/min 'unidentified' tier -- twenty times worse than anonymous
        traffic that identifies itself."""
        assert "https://" in RateLimitPolicy().user_agent
        assert TIER_LIMITS[RateLimitTier.unidentified] == 10


class TestConfigInjection:
    def test_api_url_constructs_autofamily_without_scanning_known_families(
        self, monkeypatch
    ):
        """A bad unrelated family must not break construction of this site.

        Passing ``url=`` to pywikibot.Site scans every configured family via
        ``Family.from_url``.  The explicit AutoFamily path has all the
        information it needs and never performs that process-global scan.
        """
        import pywikibot

        from wtbot.wiki.client import _make_pywikibot_site

        calls = []
        expected_site = object()

        def site(**kwargs):
            calls.append(kwargs)
            return expected_site

        monkeypatch.setattr(pywikibot, "Site", site)
        result = _make_pywikibot_site(
            pywikibot,
            WikiSettings(
                family="mywikisource",
                code="en",
                api_url="https://wikisource-debian-13.lan/w/api.php",
            ),
        )

        assert result is expected_site
        assert "url" not in calls[0]
        assert calls[0]["code"] == "mywikisource"
        family = calls[0]["fam"]
        assert family.name == "mywikisource"
        assert callable(family.protocol)

    def test_configure_sets_env_and_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYWIKIBOT_NO_USER_CONFIG", raising=False)
        from wtbot.wiki.config import configure_pywikibot

        settings = WikiSettings(
            family="mywikisource",
            code="en",
            api_url="https://wikisource-debian-13.lan/w/api.php",
            ca_bundle=str(tmp_path / "ca.pem"),
            config_dir=str(tmp_path / "pwb"),
        )
        import os

        returned = configure_pywikibot(settings)
        assert returned == str(tmp_path / "pwb")
        assert os.environ["PYWIKIBOT_DIR"] == str(tmp_path / "pwb")
        assert os.environ["PYWIKIBOT_NO_USER_CONFIG"] == "1"
        assert os.environ["REQUESTS_CA_BUNDLE"] == str(tmp_path / "ca.pem")

    def test_configure_applies_fail_fast_retry_policy(self, tmp_path):
        """Default policy is no retries: repeated failures are more likely our
        bug (missing token -> rate limited) than a flaky network, and backoff
        just hides them. The knobs stay adjustable for chaos testing later."""
        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot

        configure_pywikibot(
            WikiSettings(family="w", code="en", config_dir=str(tmp_path / "a"))
        )
        assert pwbconfig.max_retries == 0
        assert pwbconfig.retry_wait == 1.0

        configure_pywikibot(
            WikiSettings(
                family="w",
                code="en",
                config_dir=str(tmp_path / "b"),
                rate_limits=RateLimitPolicy(max_retries=3, retry_wait=2.5),
            )
        )
        assert pwbconfig.max_retries == 3
        assert pwbconfig.retry_wait == 2.5

    def test_configure_throttles_reads_not_only_writes(self, tmp_path):
        """The bug this pins: we set put_throttle (edits) and left minthrottle
        at pywikibot's 0.1s default, which permits 600 read req/min against a
        200 req/min allowance -- and an Index fan-out is almost all reads."""
        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot

        configure_pywikibot(
            WikiSettings(family="w", code="en", config_dir=str(tmp_path / "t"))
        )
        assert pwbconfig.minthrottle == 0.35  # ~170 req/min
        assert 60 / pwbconfig.minthrottle < 200
        assert pwbconfig.put_throttle == 1.0
        assert pwbconfig.maxlag == 5

    def test_throttle_settings_from_env(self):
        env = {
            "WTBOT_WIKI_READ_THROTTLE": "1.5",
            "WTBOT_WIKI_PUT_THROTTLE": "10",
            "WTBOT_WIKI_MAXLAG": "2",
        }
        policy = WikiSettings.from_env(env).rate_limits
        assert policy.read_throttle == 1.5
        assert policy.put_throttle == 10.0
        assert policy.maxlag == 2

    def test_site_read_throttle_overrides_only_the_global_read_pacing(
        self, monkeypatch
    ):
        from wtbot.model import Site

        monkeypatch.setenv("WTBOT_WIKI_READ_THROTTLE", "1.5")
        monkeypatch.setenv("WTBOT_WIKI_PUT_THROTTLE", "10")

        inherited = WikiSettings.from_site(Site(family="w", code="en"))
        local = WikiSettings.from_site(
            Site(family="local", code="en", read_throttle=0.01)
        )

        assert inherited.rate_limits.read_throttle == 1.5
        assert local.rate_limits.read_throttle == 0.01
        assert local.rate_limits.put_throttle == 10.0

    def test_site_read_throttle_reaches_pywikibot(self, tmp_path):
        import pywikibot.config as pwbconfig

        from wtbot.model import Site
        from wtbot.wiki.config import configure_pywikibot

        settings = WikiSettings.from_site(
            Site(family="local", code="en", read_throttle=0.01),
            config_dir=str(tmp_path / "local-pwb"),
        )
        configure_pywikibot(settings)

        assert settings.read_throttle == 0.01
        assert pwbconfig.minthrottle == 0.01

    def test_each_client_captures_its_site_policy_before_global_config_changes(
        self, tmp_path, monkeypatch
    ):
        import pywikibot
        import pywikibot.config as pwbconfig

        from wtbot.wiki.client import PywikibotClient

        class LazySite:
            def __init__(self):
                self._throttle = None

            @property
            def throttle(self):
                if self._throttle is None:
                    self._throttle = type(
                        "CapturedThrottle",
                        (),
                        {"mindelay": pwbconfig.minthrottle},
                    )()
                return self._throttle

            def __str__(self):
                return "fake-site"

        monkeypatch.setattr(pywikibot, "Site", lambda **kwargs: LazySite())

        fast = PywikibotClient(
            WikiSettings(
                family="local-fast",
                code="en",
                api_url="http://local-fast/api.php",
                config_dir=str(tmp_path / "pwb"),
                rate_limits=RateLimitPolicy(read_throttle=0.01),
            )
        )
        slow = PywikibotClient(
            WikiSettings(
                family="remote-slow",
                code="en",
                api_url="http://remote-slow/api.php",
                config_dir=str(tmp_path / "pwb"),
                rate_limits=RateLimitPolicy(read_throttle=0.7),
            )
        )

        assert fast.site.throttle.mindelay == 0.01
        assert slow.site.throttle.mindelay == 0.7

    def test_user_agent_states_contact_information(self, tmp_path):
        """Wikimedia's policy requires a contact URL or email and throttles
        non-conforming clients harder, so this costs request budget when wrong.
        Rendered through pywikibot's own formatter, since that is what ships."""
        import pywikibot.config as pwbconfig
        from pywikibot.comms.http import user_agent

        from wtbot.wiki.config import configure_pywikibot

        configure_pywikibot(
            WikiSettings(family="w", code="en", config_dir=str(tmp_path / "ua"))
        )
        rendered = user_agent()
        assert "wtbot" in rendered
        assert "https://github.com/tolland/wikisource-plugin" in rendered
        # A literal template must survive formatting with no placeholders left.
        assert "{" not in rendered and "}" not in rendered
        assert pwbconfig.user_agent_format  # not blanked

    def test_config_dir_is_stable_across_clients(self):
        """A fresh mkdtemp per client threw away the cookie jar and
        throttle.ctrl, so every client re-authenticated and no concurrency
        detection ever fired."""
        from wtbot.wiki.config import configure_pywikibot

        first = configure_pywikibot(WikiSettings(family="w", code="en"))
        second = configure_pywikibot(WikiSettings(family="w", code="en"))
        assert first == second

    def test_retry_policy_from_env(self):
        env = {"WTBOT_WIKI_MAX_RETRIES": "5", "WTBOT_WIKI_RETRY_WAIT": "0.5"}
        policy = WikiSettings.from_env(env).rate_limits
        assert policy.max_retries == 5
        assert policy.retry_wait == 0.5
        assert WikiSettings.from_env({}).rate_limits.max_retries == 0

    def test_configure_points_password_file_and_writes_user_config(self, tmp_path):
        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot

        settings = WikiSettings(
            family="mywikisource",
            code="en",
            username="Alice",
            password="hunter2",
            bot_name="wtbot",
            config_dir=str(tmp_path / "pwb"),
        )
        configure_pywikibot(settings)

        # configure_pywikibot points pywikibot at the password file path even
        # before write_password_entry creates the file (entry written post-Site).
        assert pwbconfig.password_file == str(tmp_path / "pwb" / "user-password.cfg")

        # user-config.py written for debugging.
        user_config = tmp_path / "pwb" / "user-config.py"
        assert user_config.is_file()
        content = user_config.read_text()
        assert "Alice" in content
        assert "user-password.cfg" in content

    def test_write_password_entry_appends_4tuple(self, tmp_path):
        import stat

        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot, write_password_entry

        settings = WikiSettings(
            family="mywikisource",
            code="en",
            username="Alice",
            password="hunter2",
            bot_name="wtbot",
            config_dir=str(tmp_path / "pwb"),
        )
        configure_pywikibot(settings)

        password_path = tmp_path / "pwb" / "user-password.cfg"
        password_path.touch()  # create empty file as configure would leave it

        write_password_entry(
            pwbconfig,
            code="mywikisource",
            family="wikisource-debian-13",
            settings=settings,
        )

        assert password_path.is_file()
        assert oct(password_path.stat().st_mode & 0o777) == oct(
            stat.S_IRUSR | stat.S_IWUSR
        )
        content = password_path.read_text()
        assert "'mywikisource'" in content
        assert "'wikisource-debian-13'" in content
        assert "'Alice'" in content
        assert "BotPassword('wtbot', 'hunter2')" in content

    def test_write_password_entry_no_duplicate_on_reconnect(self, tmp_path):
        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot, write_password_entry

        settings = WikiSettings(
            family="mywikisource",
            code="en",
            username="Alice",
            password="pw",
            config_dir=str(tmp_path / "pwb"),
        )
        configure_pywikibot(settings)
        password_path = tmp_path / "pwb" / "user-password.cfg"
        password_path.touch()

        write_password_entry(
            pwbconfig, code="en", family="mywikisource", settings=settings
        )
        write_password_entry(
            pwbconfig, code="en", family="mywikisource", settings=settings
        )
        lines = [
            line for line in password_path.read_text().splitlines() if line.strip()
        ]
        assert len(lines) == 1  # second call is a no-op

    def test_configure_api_url_replaces_wildcard_username(self, tmp_path, monkeypatch):
        import pywikibot.config as pwbconfig

        from wtbot.wiki.config import configure_pywikibot

        # Reproduce an earlier client/test having configured another account.
        monkeypatch.setattr(
            pwbconfig,
            "usernames",
            defaultdict(dict, {"*": {"*": "Admin", "en": "Admin"}}),
        )
        settings = WikiSettings(
            family="mywikisource",
            code="en",
            api_url="https://wikisource-debian-13.lan/w/api.php",
            username="Alice",
            config_dir=str(tmp_path / "pwb"),
        )
        configure_pywikibot(settings)
        # '*' wildcard must be set so AutoFamily-derived sites find the username
        assert pwbconfig.usernames.get("*", {}).get("*") == "Alice"


def test_from_env():
    s = WikiSettings.from_env(
        {"WTBOT_WIKI_FAMILY": "mywikisource", "WTBOT_WIKI_CODE": "en"}
    )
    assert s.family == "mywikisource"
    assert s.code == "en"


def test_from_env_reads_credentials():
    s = WikiSettings.from_env(
        {
            "WTBOT_WIKI_FAMILY": "mywikisource",
            "WTBOT_WIKI_CODE": "en",
            "WTBOT_WIKI_USERNAME": "Alice",
            "WTBOT_WIKI_PASSWORD": "hunter2",
            "WTBOT_WIKI_BOTNAME": "wtbot",
        }
    )
    assert s.username == "Alice"
    assert s.password == "hunter2"
    assert s.bot_name == "wtbot"


class _FakeSiteRow:
    family = "mywikisource"
    code = "en"
    api_url = "https://wikisource-debian-13.lan/w/api.php"
    read_throttle = None


def test_from_site_has_no_credentials_without_overrides(monkeypatch):
    # Credentials no longer fall back to env -- they must be passed explicitly
    # by the DB-aware factory (which reads SiteCredential rows) to keep each
    # site's credentials independent when multiple sites are configured.
    monkeypatch.setenv("WTBOT_WIKI_USERNAME", "Alice")
    monkeypatch.setenv("WTBOT_WIKI_PASSWORD", "hunter2")

    s = WikiSettings.from_site(_FakeSiteRow())

    assert s.family == "mywikisource"
    assert s.code == "en"
    assert s.username is None
    assert s.password is None


def test_from_site_explicit_credential_overrides():
    s = WikiSettings.from_site(
        _FakeSiteRow(), username="Bob", password="swordfish", bot_name="mybot"
    )
    assert s.username == "Bob"
    assert s.password == "swordfish"
    assert s.bot_name == "mybot"
