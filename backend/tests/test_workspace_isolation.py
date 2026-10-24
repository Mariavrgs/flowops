from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import Actor, register_actor

pytestmark = pytest.mark.db


def _make_category(actor: Actor, name: str = "Payments") -> str:
    response = actor.post(
        f"/api/workspaces/{actor.workspace_id}/categories", {"name": name, "kind": "bug"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_cannot_list_another_workspaces_categories() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    _make_category(bob)
    assert alice.get(f"/api/workspaces/{bob.workspace_id}/categories").status_code == 404


def test_cannot_create_in_another_workspace() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    response = alice.post(
        f"/api/workspaces/{bob.workspace_id}/categories", {"name": "Hack", "kind": "bug"}
    )
    assert response.status_code == 404
    assert [
        c["name"] for c in bob.get(f"/api/workspaces/{bob.workspace_id}/categories").json()
    ] == []


def test_cannot_read_foreign_category_by_id_through_either_workspace_path() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    bobs_category = _make_category(bob)
    # Through bob's workspace (not a member) and through alice's own workspace (wrong owner).
    assert (
        alice.get(f"/api/workspaces/{bob.workspace_id}/categories/{bobs_category}").status_code
        == 404
    )
    assert (
        alice.get(f"/api/workspaces/{alice.workspace_id}/categories/{bobs_category}").status_code
        == 404
    )
    assert (
        bob.get(f"/api/workspaces/{bob.workspace_id}/categories/{bobs_category}").status_code == 200
    )


def test_foreign_and_nonexistent_workspaces_are_indistinguishable() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    foreign = alice.get(f"/api/workspaces/{bob.workspace_id}/categories")
    missing = alice.get(f"/api/workspaces/{uuid4()}/categories")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_unauthenticated_access_is_rejected() -> None:
    bob = register_actor("bob@example.com")
    assert TestClient(app).get(f"/api/workspaces/{bob.workspace_id}/categories").status_code == 401


def test_same_category_name_allowed_in_different_workspaces_but_not_within_one() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    _make_category(alice, "Payments")
    _make_category(bob, "Payments")
    duplicate = alice.post(
        f"/api/workspaces/{alice.workspace_id}/categories", {"name": "Payments", "kind": "bug"}
    )
    assert duplicate.status_code == 409
