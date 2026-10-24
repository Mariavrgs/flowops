import pytest

from tests.helpers import Actor, add_member, register_actor

pytestmark = pytest.mark.db


def _categories_url(actor: Actor) -> str:
    return f"/api/workspaces/{actor.workspace_id}/categories"


def test_viewer_can_read_but_not_create() -> None:
    admin, viewer = register_actor("admin@example.com"), register_actor("viewer@example.com")
    assert add_member(admin, viewer, "viewer").status_code == 201
    url = _categories_url(admin)
    assert viewer.client.get(url).status_code == 200
    assert viewer.post(url, {"name": "X", "kind": "bug"}).status_code == 403


def test_agent_cannot_manage_categories() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    assert add_member(admin, agent, "agent").status_code == 201
    assert agent.post(_categories_url(admin), {"name": "X", "kind": "bug"}).status_code == 403


def test_admin_can_create_category() -> None:
    admin = register_actor("admin@example.com")
    response = admin.post(_categories_url(admin), {"name": "Payments", "kind": "incident"})
    assert response.status_code == 201
    assert response.json()["kind"] == "incident"


def test_invalid_category_kind_is_rejected() -> None:
    admin = register_actor("admin@example.com")
    assert admin.post(_categories_url(admin), {"name": "X", "kind": "task"}).status_code == 422


def test_only_admin_can_add_members() -> None:
    admin, agent, other = (register_actor(f"{n}@example.com") for n in ("admin", "agent", "other"))
    assert add_member(admin, agent, "agent").status_code == 201
    forbidden = agent.post(
        f"/api/workspaces/{admin.workspace_id}/members", {"email": other.email, "role": "viewer"}
    )
    assert forbidden.status_code == 403


def test_add_member_error_cases() -> None:
    admin, user = register_actor("admin@example.com"), register_actor("user@example.com")
    url = f"/api/workspaces/{admin.workspace_id}/members"
    assert admin.post(url, {"email": user.email, "role": "owner"}).status_code == 422
    assert admin.post(url, {"email": "ghost@example.com", "role": "viewer"}).status_code == 404
    assert add_member(admin, user, "viewer").status_code == 201
    assert add_member(admin, user, "agent").status_code == 409
