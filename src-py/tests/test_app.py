#
#

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_site(client):
    payload = {"family": "mywikisource", "code": "en", "articlepath": "/wiki/$1"}
    resp = client.post("/sites/", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["pk"] is not None
    assert created["family"] == "mywikisource"

    listed = client.get("/sites/").json()
    assert len(listed) == 1
    assert listed[0]["code"] == "en"


def test_get_missing_site_404(client):
    assert client.get("/sites/999").status_code == 404
