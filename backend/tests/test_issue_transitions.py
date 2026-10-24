import pytest

from tests.helpers import (
    add_member,
    issues_url,
    make_category,
    make_issue,
    register_actor,
    transition,
)

pytestmark = pytest.mark.db


def test_full_lifecycle_records_every_state_change() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    iid, version = issue["id"], issue["version"]
    steps = [
        ("in_progress", None),
        ("blocked", "waiting for vendor"),
        ("in_progress", None),
        ("resolved", None),
        ("closed", None),
    ]
    for to_status, reason in steps:
        response = transition(admin, iid, to_status, version, reason)
        assert response.status_code == 200, response.text
        version = response.json()["version"]
    assert version == 6

    history = admin.get(f"{issues_url(admin)}/{iid}/history").json()
    assert [(e["from_status"], e["to_status"]) for e in history["status_events"]] == [
        (None, "open"),
        ("open", "in_progress"),
        ("in_progress", "blocked"),
        ("blocked", "in_progress"),
        ("in_progress", "resolved"),
        ("resolved", "closed"),
    ]
    blocked_event = history["status_events"][2]
    assert blocked_event["reason"] == "waiting for vendor"
    assert blocked_event["actor_id"] == admin.user_id
    # Event timestamps never go backwards.
    times = [e["occurred_at"] for e in history["status_events"]]
    assert times == sorted(times)
    # The audit log has a matching "status" entry for each of the five transitions.
    assert [c["field"] for c in history["changes"]] == ["status"] * 5


def test_blocking_requires_a_reason_and_leaves_the_issue_untouched() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    response = transition(admin, issue["id"], "blocked", issue["version"], None)
    assert response.status_code == 422
    current = admin.get(f"{issues_url(admin)}/{issue['id']}").json()
    assert current["status"] == "open" and current["version"] == 1


def test_invalid_transition_returns_allowed_targets() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    response = transition(admin, issue["id"], "closed", issue["version"])
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["current_status"] == "open"
    assert detail["allowed_transitions"] == ["in_progress", "blocked", "resolved"]


def test_transition_to_the_same_status_is_invalid() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    assert transition(admin, issue["id"], "open", issue["version"]).status_code == 422


def test_reopen_requires_reason_and_increments_reopen_count() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    version = transition(admin, issue["id"], "resolved", issue["version"]).json()["version"]

    assert transition(admin, issue["id"], "open", version).status_code == 422  # no reason
    reopened = transition(admin, issue["id"], "open", version, "regression in v2.1")
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "open" and reopened.json()["reopen_count"] == 1

    # Resolve and reopen again: the counter keeps counting.
    version = transition(admin, issue["id"], "resolved", reopened.json()["version"]).json()[
        "version"
    ]
    again = transition(admin, issue["id"], "open", version, "still broken")
    assert again.json()["reopen_count"] == 2


def test_closed_is_terminal() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    version = issue["version"]
    for status in ("resolved", "closed"):
        version = transition(admin, issue["id"], status, version).json()["version"]
    for target in ("open", "in_progress", "blocked", "resolved"):
        assert transition(admin, issue["id"], target, version, "reason").status_code == 422


def test_viewer_cannot_transition_and_agent_can() -> None:
    admin, viewer, agent = (
        register_actor(f"{n}@example.com") for n in ("admin", "viewer", "agent")
    )
    add_member(admin, viewer, "viewer")
    add_member(admin, agent, "agent")
    issue = make_issue(admin, make_category(admin))
    url = f"{issues_url(admin)}/{issue['id']}/transitions"
    body = {"to_status": "in_progress", "version": 1}
    assert (
        viewer.client.post(url, json=body, headers={"X-CSRF-Token": viewer.csrf}).status_code == 403
    )
    assert (
        agent.client.post(url, json=body, headers={"X-CSRF-Token": agent.csrf}).status_code == 200
    )


def test_transition_in_another_workspace_is_404() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    bobs_issue = make_issue(bob, make_category(bob))
    response = alice.post(
        f"{issues_url(bob)}/{bobs_issue['id']}/transitions",
        {"to_status": "in_progress", "version": 1},
    )
    assert response.status_code == 404
    unchanged = bob.get(f"{issues_url(bob)}/{bobs_issue['id']}").json()
    assert unchanged["status"] == "open" and unchanged["version"] == 1
