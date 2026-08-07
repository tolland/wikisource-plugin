#
#


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_site(client):
    payload = {
        "label": "local",
        "family": "mywikisource",
        "code": "en",
        "articlepath": "/wiki/$1",
    }
    resp = client.post("/sites/", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["pk"] is not None
    assert created["family"] == "mywikisource"

    listed = client.get("/sites/").json()
    assert len(listed) == 1
    assert listed[0]["code"] == "en"


def test_update_site(client):
    created = client.post(
        "/sites/", json={"label": "local", "family": "mywikisource", "code": "en"}
    ).json()

    resp = client.put(
        f"/sites/{created['pk']}",
        json={
            "family": "mywikisource",
            "code": "fr",
            "articlepath": "/wiki/$1",
            "api_url": "https://example.test/w/api.php",
            "label": "Example",
        },
    )

    assert resp.status_code == 200
    updated = resp.json()
    assert updated["code"] == "fr"
    assert updated["api_url"] == "https://example.test/w/api.php"
    assert updated["label"] == "Example"


def test_get_missing_site_404(client):
    assert client.get("/sites/999").status_code == 404
