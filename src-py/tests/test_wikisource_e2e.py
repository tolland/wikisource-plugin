import requests


def test_wikisource_api_has_proofreadpage(wikisource) -> None:
    response = requests.get(
        wikisource.api_url,
        params={
            "action": "query",
            "meta": "siteinfo",
            "siprop": "general|extensions|namespaces",
            "format": "json",
        },
        timeout=10,
    )

    response.raise_for_status()
    siteinfo = response.json()["query"]

    assert siteinfo["general"]["sitename"] == "Test Wikisource"
    assert any(ext["name"] == "ProofreadPage" for ext in siteinfo["extensions"])
    assert siteinfo["namespaces"]["104"]["*"] == "Page"
    assert siteinfo["namespaces"]["106"]["*"] == "Index"
