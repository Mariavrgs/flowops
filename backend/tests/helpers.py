from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from app.main import app

PASSWORD = "correct horse battery staple"


@dataclass
class Actor:
    """A logged-in user with their own cookie jar and their own first workspace."""

    client: TestClient
    email: str
    csrf: str
    workspace_id: str
    user_id: str

    def get(self, url: str) -> Response:
        return self.client.get(url)

    def post(self, url: str, json: dict[str, Any] | None = None) -> Response:
        return self.client.post(url, json=json or {}, headers={"X-CSRF-Token": self.csrf})

    def put(self, url: str, json: dict[str, Any]) -> Response:
        return self.client.put(url, json=json, headers={"X-CSRF-Token": self.csrf})


def register_actor(email: str, workspace_name: str = "Team") -> Actor:
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "name": email.split("@")[0],
            "workspace_name": workspace_name,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Actor(
        client=client,
        email=email,
        csrf=body["csrf_token"],
        workspace_id=body["memberships"][0]["workspace_id"],
        user_id=body["user"]["id"],
    )


def add_member(admin: Actor, member: Actor, role: str) -> Response:
    return admin.post(
        f"/api/workspaces/{admin.workspace_id}/members", {"email": member.email, "role": role}
    )


def make_category(actor: Actor, name: str = "Payments") -> str:
    response = actor.post(
        f"/api/workspaces/{actor.workspace_id}/categories", {"name": name, "kind": "bug"}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def issues_url(actor: Actor) -> str:
    return f"/api/workspaces/{actor.workspace_id}/issues"


def make_issue(actor: Actor, category_id: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"title": "Checkout fails", "category_id": category_id, **overrides}
    response = actor.post(issues_url(actor), body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def transition(
    actor: Actor, issue_id: str, to_status: str, version: int, reason: str | None = None
) -> Response:
    return actor.post(
        f"{issues_url(actor)}/{issue_id}/transitions",
        {"to_status": to_status, "version": version, "reason": reason},
    )


def patch(actor: Actor, issue_id: str, body: dict[str, Any]) -> Response:
    return actor.client.patch(
        f"{issues_url(actor)}/{issue_id}", json=body, headers={"X-CSRF-Token": actor.csrf}
    )


DEFAULT_CONFIG: dict[str, int] = {
    "weight_impact": 30,
    "weight_urgency": 25,
    "weight_affected_users": 20,
    "weight_no_workaround": 15,
    "weight_deadline": 10,
    "p1_min": 75,
    "p2_min": 50,
    "p3_min": 25,
}


def config_url(actor: Actor) -> str:
    return f"/api/workspaces/{actor.workspace_id}/priority-config"


def put_config(actor: Actor, version: int, **overrides: int) -> Response:
    return actor.put(config_url(actor), {**DEFAULT_CONFIG, "version": version, **overrides})


def recalculate_url(actor: Actor) -> str:
    return f"/api/workspaces/{actor.workspace_id}/priority/recalculate"


def explanation(actor: Actor, issue_id: str) -> dict[str, Any]:
    response = actor.get(f"{issues_url(actor)}/{issue_id}/priority")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# Puts all the weight on "no workaround": an issue without a workaround scores 100.
ONLY_NO_WORKAROUND: dict[str, int] = {
    "weight_impact": 0,
    "weight_urgency": 0,
    "weight_affected_users": 0,
    "weight_no_workaround": 100,
    "weight_deadline": 0,
}
