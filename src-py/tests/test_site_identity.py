import ast
from pathlib import Path

import pytest

"""One place creates a wiki, and it is the one an operator goes to.

A `Site` used to be conjured from whatever `family`/`code`/`api_url` a fetch
request happened to carry. A typo therefore *registered a new wiki* -- with no
credentials -- and read from it anonymously, and the first sign was a log line
long after the fact. Sites are now addressed by their registered `label`, and
registration is its own deliberate step where credentials can be attached.

That is an invariant, not a past cleanup, and it has already come back once: the
viewer's fetch form was still posting `family`/`code`/`api_url` to an endpoint
that wants a label, so every submit 422'd. These tests fail when it creeps back
rather than leaving it to be re-audited by hand.

What is *not* forbidden: reading those fields. `family` and `code` are fine to
display, to derive a scope string from, and to look a site up by -- a lookup
returns None for an unknown pair, where a create would have invented one. The
line is writing, and specifically writing from request input.
"""

API = Path(__file__).resolve().parents[1] / "wtbot" / "api"
VIEWER = Path(__file__).resolve().parents[2] / "viewer" / "src"

#: The only module allowed to build a Site from a request body: the CRUD one.
SITE_CRUD = "sites.py"

#: Fields that identify *where* a wiki is. Accepting them as writable request
#: input anywhere else is how a typo becomes a new wiki.
LOCATION_FIELDS = {"family", "code", "api_url"}


def _api_modules() -> list[Path]:
    return sorted(p for p in API.glob("*.py") if p.name != "__init__.py")


def test_only_the_site_crud_module_constructs_a_site() -> None:
    """`Site(...)` outside the registration endpoint is the bug itself."""
    offenders = []
    for path in _api_modules():
        if path.name == SITE_CRUD:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Site"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], (
        "these routers construct a Site row: "
        + ", ".join(offenders)
        + ". Sites are registered through POST /sites and addressed by label "
        "everywhere else."
    )


def _body_models(tree: ast.Module) -> set[str]:
    """Model names used as a **request body** by some route in this module.

    A FastAPI body parameter is one annotated with a model and given no
    `Query(...)`/`Depends(...)` default. Narrowing to these is what keeps the
    check honest: a response model naming `family` is the UI display case,
    which is fine, and `OcrModelOut.code` is a *language* code that merely
    shares a word with a wiki's.
    """
    models = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(b.id == "BaseModel" for b in node.bases if isinstance(b, ast.Name))
    }
    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = node.args
        defaults: list[ast.expr | None] = [None] * (
            len(args.args) - len(args.defaults)
        ) + list(args.defaults)
        for arg, default in zip(
            args.args + args.kwonlyargs, defaults + args.kw_defaults
        ):
            names = (
                {
                    child.id
                    for child in ast.walk(arg.annotation)
                    if isinstance(child, ast.Name)
                }
                if arg.annotation is not None
                else set()
            )
            if not (names & models):
                continue
            if isinstance(default, ast.Call):
                continue  # Query(...)/Depends(...): not a body
            used |= names & models
    return used


def _fields(tree: ast.Module, name: str) -> list[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return [
                (statement.lineno, statement.target.id)
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            ]
    return []


def test_no_router_takes_a_wiki_location_as_writable_input() -> None:
    """A request *body* naming family/code/api_url is the shape that used to
    create wikis by accident.

    Query parameters are exempt: `GET /pages/resolve?family=&code=&title=` is a
    lookup that returns None for an unknown pair, which is the opposite of
    inventing one. Response models are exempt too -- displaying which wiki a
    row belongs to is the point of having the field.
    """
    offenders = []
    for path in _api_modules():
        if path.name == SITE_CRUD:
            continue
        tree = ast.parse(path.read_text())
        for model in sorted(_body_models(tree)):
            for lineno, field in _fields(tree, model):
                if field in LOCATION_FIELDS:
                    offenders.append(f"{path.name}:{lineno} {model}.{field}")
    assert offenders == [], (
        "these request models take a wiki's location as input: "
        + ", ".join(offenders)
        + ". Take a registered `label` instead -- a typo in a label is a 404, "
        "a typo in an api_url is a new wiki nobody configured."
    )


@pytest.mark.skipif(not VIEWER.exists(), reason="viewer sources not present")
def test_the_viewer_sends_a_label_rather_than_a_location() -> None:
    """The fetch form posted family/code/api_url to an endpoint that requires
    a label, so every submit 422'd -- a bug that survived because nothing
    checked the two sides agreed."""
    types = (VIEWER / "lib" / "types.ts").read_text()
    start = types.index("export interface FetchCreate")
    body = types[start : types.index("}", start)]

    assert "label" in body, "FetchCreate must name the registered site"
    for field in ("family", "code:", "api_url"):
        assert field not in body, (
            f"FetchCreate still carries {field!r}; a fetch names a registered "
            "site by label and never creates one"
        )
