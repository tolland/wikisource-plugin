from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from wtbot.main import create_app

"""Pins the routing constraint created by five routers sharing /pages.

`annotations`, `ocr`, `page_meta`, `page_nav` and `pages` all mount under
/pages. Nothing about APIRouter isolates them from each other: including a
router splices its path operations into one ordered table, and matching is
first-match-wins. This is the same rule FastAPI documents for two path
operations in one file (`/users/me` must be declared before
`/users/{user_id}`) -- it just becomes invisible when the two operations
live in different modules.

`pages` owns `GET /pages/{page_pk}`, which matches any single segment, so a
static sibling registered after it never runs. The shadowed request does not
404, it 422s on parsing "nav" as an int, which is why this is worth a test
rather than a comment.
"""

# Single-segment /pages routes -- the ones {page_pk} can swallow. Deeper
# paths like /pages/ocr/run are structurally safe from it.
_SHADOWABLE = [
    "/pages/nav",
    "/pages/resolve",
    "/pages/annotations",
    "/pages/text-anchors",
    "/pages/box-links",
]


def _paths_in_registration_order(app) -> list[str]:
    # The OpenAPI paths object is built by walking routes in order, and dicts
    # preserve insertion order -- so this is the routing table's order
    # without reaching into FastAPI internals.
    return list(app.openapi()["paths"])


def test_static_pages_routes_are_registered_before_the_catch_all(engine):
    paths = _paths_in_registration_order(create_app(engine=engine))
    catch_all = paths.index("/pages/{page_pk}")
    for path in _SHADOWABLE:
        assert path in paths, f"{path} is not registered at all"
        assert paths.index(path) < catch_all, (
            f"{path} is registered after /pages/{{page_pk}} and is shadowed by "
            "it -- move its router above pages.router in create_app()"
        )


def test_no_pages_route_is_added_after_the_catch_all(engine):
    """Catches shadowing of routes this test does not know about yet."""
    paths = _paths_in_registration_order(create_app(engine=engine))
    after = paths[paths.index("/pages/{page_pk}") + 1 :]
    assert not [
        p for p in after if p.startswith("/pages/")
    ], f"routes registered after the /pages catch-all: {after}"


def test_static_pages_routes_reach_their_own_handler(client):
    """Behavioural counterpart: called with no query string these answer 422
    for their own missing `path` param. What must never appear is a 422
    blaming `page_pk` -- that is {page_pk} having eaten the request."""
    shadowed_loc = ("path", "page_pk")
    for path in _SHADOWABLE:
        detail = client.get(path).json().get("detail", [])
        if not isinstance(detail, list):  # a handler's own str detail; fine
            continue
        locs = [tuple(item.get("loc", ())) for item in detail]
        assert (
            shadowed_loc not in locs
        ), f"{path} was matched by /pages/{{page_pk}}, not its own handler"


def test_shadowing_demonstrated():
    """Why the ordering matters, in isolation: same two routes, two include
    orders, two different outcomes. Fails here if FastAPI ever starts
    prioritising static segments over path params on its own -- at which
    point the constraint above can be dropped."""

    def build(dynamic_first: bool) -> FastAPI:
        dynamic = APIRouter(prefix="/pages")
        static = APIRouter(prefix="/pages")

        @dynamic.get("/{page_pk}")
        def _get_page(page_pk: int) -> dict[str, str]:
            return {"hit": "dynamic"}

        @static.get("/nav")
        def _nav() -> dict[str, str]:
            return {"hit": "static"}

        app = FastAPI()
        for router in (dynamic, static) if dynamic_first else (static, dynamic):
            app.include_router(router)
        return app

    assert TestClient(build(dynamic_first=True)).get("/pages/nav").status_code == 422

    ok = TestClient(build(dynamic_first=False)).get("/pages/nav")
    assert ok.status_code == 200
    assert ok.json() == {"hit": "static"}
