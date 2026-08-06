from collections import defaultdict

import pytest

from wtbot.model import NsRole
from wtbot.settings import WikiSettings
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.dispatch import Handling, classify, classify_remote
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


class TestConfigInjection:
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
                max_retries=3,
                retry_wait=2.5,
            )
        )
        assert pwbconfig.max_retries == 3
        assert pwbconfig.retry_wait == 2.5

    def test_retry_policy_from_env(self):
        env = {"WTBOT_WIKI_MAX_RETRIES": "5", "WTBOT_WIKI_RETRY_WAIT": "0.5"}
        settings = WikiSettings.from_env(env)
        assert settings.max_retries == 5
        assert settings.retry_wait == 0.5
        assert WikiSettings.from_env({}).max_retries == 0

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
