import pytest

from wtbot.settings import WikiSettings
from wtbot.sqlmodel import NsRole
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.dispatch import Handling, classify, classify_remote
from wtbot.wiki.types import PageNotFound, RemotePage


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


def test_from_env():
    s = WikiSettings.from_env(
        {"WTBOT_WIKI_FAMILY": "mywikisource", "WTBOT_WIKI_CODE": "en"}
    )
    assert s.family == "mywikisource"
    assert s.code == "en"
