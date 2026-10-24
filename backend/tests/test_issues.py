from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.helpers import (
    add_member,
    issues_url,
    make_category,
    make_issue,
    patch,
    register_actor,
    transition,
)

pytestmark = pytest.mark.db


def _future(days: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def test_create_issue_defaults_and_initial_event() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    assert issue["status"] == "open"
    assert issue["version"] == 1
    assert issue["priority"] == 3  # computed: default inputs score 33.33 -> P3
    assert issue["priority_score"] == pytest.approx(33.33)
    assert issue["priority_override_reason"] is None
    assert issue["reopen_count"] == 0
    assert issue["reporter_id"] == admin.user_id

    history = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()
    assert [(e["from_status"], e["to_status"]) for e in history["status_events"]] == [
        (None, "open")
    ]
    assert history["status_events"][0]["occurred_at"] == issue["created_at"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"priority": 5, "priority_override_reason": "x"},
        {"priority": 0, "priority_override_reason": "x"},
        {"impact": 5},
        {"urgency": 0},
        {"affected_users": -1},
        {"title": "   "},
        {"due_at": "2030-01-01T10:00:00"},  # naive datetime: timezone is mandatory
        {"due_at": "2000-01-01T10:00:00+00:00"},  # in the past
    ],
)
def test_create_rejects_invalid_input(overrides: dict[str, object]) -> None:
    admin = register_actor("admin@example.com")
    body = {"title": "x", "category_id": make_category(admin), **overrides}
    assert admin.post(issues_url(admin), body).status_code == 422


def test_create_rejects_category_from_another_workspace() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    bobs_category = make_category(bob)
    response = alice.post(issues_url(alice), {"title": "x", "category_id": bobs_category})
    assert response.status_code == 422


def test_create_rejects_assignee_who_is_not_a_member() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    response = alice.post(
        issues_url(alice),
        {"title": "x", "category_id": make_category(alice), "assignee_id": bob.user_id},
    )
    assert response.status_code == 422


def test_create_with_member_assignee_and_due_date() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    assert add_member(admin, agent, "agent").status_code == 201
    issue = make_issue(
        admin,
        make_category(admin),
        assignee_id=agent.user_id,
        due_at=_future(),
        priority=1,
        priority_override_reason="Customer escalation",
    )
    assert issue["assignee_id"] == agent.user_id and issue["priority"] == 1


def test_viewer_can_read_but_not_write() -> None:
    admin, viewer = register_actor("admin@example.com"), register_actor("viewer@example.com")
    assert add_member(admin, viewer, "viewer").status_code == 201
    category = make_category(admin)
    issue = make_issue(admin, category)
    url = issues_url(admin)
    assert viewer.get(f"{url}/{issue['id']}").status_code == 200
    assert viewer.post(url, {"title": "x", "category_id": category}).status_code == 403
    forged = viewer.client.patch(
        f"{url}/{issue['id']}",
        json={"version": 1, "title": "y"},
        headers={"X-CSRF-Token": viewer.csrf},
    )
    assert forged.status_code == 403


def test_issue_of_another_workspace_is_invisible() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    bobs_issue = make_issue(bob, make_category(bob))
    # Through bob's workspace path (alice is not a member) and through her own (wrong owner).
    assert alice.get(f"{issues_url(bob)}/{bobs_issue['id']}").status_code == 404
    assert alice.get(f"{issues_url(alice)}/{bobs_issue['id']}").status_code == 404
    assert alice.get(f"{issues_url(alice)}").json() == []
    assert alice.get(f"{issues_url(bob)}").status_code == 404


def test_update_records_old_and_new_values_and_bumps_version() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    response = patch(admin, issue["id"], {"version": 1, "title": "New title", "impact": 4})
    assert response.status_code == 200
    assert response.json()["version"] == 2

    changes = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()["changes"]
    by_field = {c["field"]: c for c in changes}
    assert by_field["title"]["old_value"] == "Checkout fails"
    assert by_field["title"]["new_value"] == "New title"
    assert by_field["impact"]["old_value"] == 2 and by_field["impact"]["new_value"] == 4
    assert by_field["impact"]["source"] == "user"
    # impact 4 raises the score to 53.33, so the computed priority moves from P3 to P2
    assert by_field["priority"]["old_value"] == 3 and by_field["priority"]["new_value"] == 2
    assert by_field["priority"]["source"] == "derived"
    assert all(c["actor_id"] == admin.user_id and c["version"] == 2 for c in changes)


def test_update_that_changes_nothing_does_not_bump_the_version() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    response = patch(admin, issue["id"], {"version": 1, "title": "Checkout fails", "impact": 2})
    assert response.status_code == 200
    assert response.json()["version"] == 1


def test_omitted_vs_null_fields() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    add_member(admin, agent, "agent")
    issue = make_issue(admin, make_category(admin), assignee_id=agent.user_id, due_at=_future())

    untouched = patch(admin, issue["id"], {"version": 1, "title": "Other"}).json()
    assert untouched["assignee_id"] == agent.user_id and untouched["due_at"] is not None

    cleared = patch(admin, issue["id"], {"version": 2, "assignee_id": None, "due_at": None}).json()
    assert cleared["assignee_id"] is None and cleared["due_at"] is None


def test_update_rejects_null_for_required_fields_and_missing_version() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    assert patch(admin, issue["id"], {"version": 1, "title": None}).status_code == 422
    assert patch(admin, issue["id"], {"title": "x"}).status_code == 422


def test_update_rejects_due_date_before_creation() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    response = patch(admin, issue["id"], {"version": 1, "due_at": "2000-01-01T00:00:00+00:00"})
    assert response.status_code == 422


def test_closed_issue_is_read_only() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    version = issue["version"]
    for status in ("resolved", "closed"):
        version = transition(admin, issue["id"], status, version).json()["version"]
    assert patch(admin, issue["id"], {"version": version, "title": "x"}).status_code == 422


def test_unknown_issue_returns_404() -> None:
    admin = register_actor("admin@example.com")
    assert admin.get(f"{issues_url(admin)}/{uuid4()}").status_code == 404
    assert patch(admin, str(uuid4()), {"version": 1, "title": "x"}).status_code == 404
