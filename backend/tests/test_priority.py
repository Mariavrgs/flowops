import pytest

from tests.helpers import (
    DEFAULT_CONFIG,
    ONLY_NO_WORKAROUND,
    add_member,
    config_url,
    explanation,
    issues_url,
    make_category,
    make_issue,
    patch,
    put_config,
    recalculate_url,
    register_actor,
    transition,
)

pytestmark = pytest.mark.db


# ---- computed priority and its explanation ----------------------------------------------------


def test_create_computes_score_and_explains_it() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    exp = explanation(admin, issue["id"])

    assert [c["key"] for c in exp["criteria"]] == [
        "impact",
        "urgency",
        "affected_users",
        "no_workaround",
        "deadline",
    ]
    assert sum(c["points"] for c in exp["criteria"]) == pytest.approx(exp["score"])
    assert exp["score"] == pytest.approx(33.33)
    assert exp["computed_priority"] == exp["effective_priority"] == 3
    assert exp["overridden"] is False and exp["stale"] is False
    assert exp["config_version"] == 0  # defaults, nothing stored yet
    assert "P3" in exp["summary"]


def test_severe_issue_is_p1() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin), impact=4, urgency=4, affected_users=5000)
    assert issue["priority"] == 1
    assert issue["priority_score"] == pytest.approx(90.0)  # 30 + 25 + 20 + 15 + 0 (no due date)


def test_changing_inputs_after_opening_recomputes_priority_and_logs_it() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    updated = patch(admin, issue["id"], {"version": 1, "impact": 4, "has_workaround": True}).json()
    # impact 4 -> 30 ; urgency 2 -> 8.33 ; users 1 -> 0 ; workaround -> 4.50 ; no due date -> 0
    assert updated["priority_score"] == pytest.approx(42.83)
    assert updated["priority"] == 3 and updated["version"] == 2

    worse = patch(admin, issue["id"], {"version": 2, "urgency": 4, "affected_users": 500}).json()
    # 30 + 25 + 15 + 4.5 = 74.5 -> P2 (just below the P1 threshold of 75)
    assert worse["priority_score"] == pytest.approx(74.5)
    assert worse["priority"] == 2

    changes = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()["changes"]
    derived = [(c["old_value"], c["new_value"]) for c in changes if c["source"] == "derived"]
    assert derived == [(3, 2)]  # only the second edit moved the band


# ---- manual override ----------------------------------------------------------------------------


def test_manual_override_wins_but_score_keeps_updating_and_override_can_be_removed() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(
        admin, make_category(admin), priority=1, priority_override_reason="Executive escalation"
    )
    assert issue["priority"] == 1 and issue["priority_override_reason"] == "Executive escalation"
    exp = explanation(admin, issue["id"])
    assert exp["overridden"] is True
    assert exp["computed_priority"] == 3 and exp["effective_priority"] == 1

    # Inputs drop: the score follows, the overridden priority does not move.
    lowered = patch(admin, issue["id"], {"version": 1, "impact": 1, "urgency": 1}).json()
    assert lowered["priority_score"] == pytest.approx(15.0)
    assert lowered["priority"] == 1

    # Removing the override returns to the computed priority (15 < 25 -> P4) and logs why.
    back = patch(admin, issue["id"], {"version": 2, "priority_override_reason": None}).json()
    assert back["priority"] == 4 and back["priority_override_reason"] is None

    changes = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()["changes"]
    by_field_and_source = {(c["field"], c["source"]): c for c in changes}
    removed = by_field_and_source[("priority_override_reason", "user")]
    assert removed["old_value"] == "Executive escalation" and removed["new_value"] is None
    moved = by_field_and_source[("priority", "derived")]
    assert (moved["old_value"], moved["new_value"]) == (1, 4)


def test_changing_the_override_by_hand_is_logged_as_a_user_change() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    result = patch(
        admin,
        issue["id"],
        {"version": 1, "priority": 1, "priority_override_reason": "Major client"},
    )
    assert result.status_code == 200 and result.json()["priority"] == 1
    changes = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()["changes"]
    assert {(c["field"], c["source"]) for c in changes} == {
        ("priority", "user"),
        ("priority_override_reason", "user"),
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"priority": 1},  # priority without a reason
        {"priority_override_reason": "because"},  # reason without a priority
        {"priority": 1, "priority_override_reason": "   "},  # blank reason
    ],
)
def test_override_must_be_a_priority_and_reason_pair_on_create(
    overrides: dict[str, object],
) -> None:
    admin = register_actor("admin@example.com")
    body = {"title": "x", "category_id": make_category(admin), **overrides}
    assert admin.post(issues_url(admin), body).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"version": 1, "priority": 2},
        {"version": 1, "priority": None, "priority_override_reason": "because"},
        {"version": 1, "priority_override_reason": "because"},
        {"version": 1, "impact": None},
    ],
)
def test_invalid_override_or_null_on_update_is_rejected(body: dict[str, object]) -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))
    assert patch(admin, issue["id"], body).status_code == 422


# ---- configuration ---------------------------------------------------------------------------


def test_default_configuration_then_admin_update() -> None:
    admin = register_actor("admin@example.com")
    initial = admin.get(config_url(admin)).json()
    assert (
        initial["version"] == 0 and initial["weight_impact"] == 30 and initial["updated_at"] is None
    )

    saved = put_config(admin, 0, weight_impact=40, weight_deadline=0)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1 and saved.json()["updated_by"] == admin.user_id
    assert admin.get(config_url(admin)).json()["weight_impact"] == 40


def test_stale_configuration_version_returns_409() -> None:
    admin = register_actor("admin@example.com")
    assert put_config(admin, 0).status_code == 200
    stale = put_config(admin, 0, weight_impact=50)
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["version"] == 1


def test_only_admins_change_the_configuration() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    add_member(admin, agent, "agent")
    assert agent.get(config_url(admin)).status_code == 200
    assert agent.put(config_url(admin), {**DEFAULT_CONFIG, "version": 0}).status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "weight_impact": 0,
            "weight_urgency": 0,
            "weight_affected_users": 0,
            "weight_no_workaround": 0,
            "weight_deadline": 0,
        },  # fmt: skip
        {"p1_min": 50, "p2_min": 50},
        {"p1_min": 40, "p2_min": 50},
        {"weight_impact": -1},
        {"p3_min": 0},
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict[str, int]) -> None:
    admin = register_actor("admin@example.com")
    assert put_config(admin, 0, **overrides).status_code == 422


def test_configuration_is_isolated_between_workspaces() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    assert put_config(alice, 0, weight_impact=99).status_code == 200
    assert bob.get(config_url(bob)).json()["version"] == 0
    assert alice.get(config_url(bob)).status_code == 404
    assert alice.put(config_url(bob), {**DEFAULT_CONFIG, "version": 0}).status_code == 404


def test_new_issues_use_the_workspace_configuration() -> None:
    admin = register_actor("admin@example.com")
    assert put_config(admin, 0, **ONLY_NO_WORKAROUND).status_code == 200
    issue = make_issue(admin, make_category(admin))  # no workaround -> factor 1 * 100%
    assert issue["priority_score"] == pytest.approx(100.0) and issue["priority"] == 1
    assert explanation(admin, issue["id"])["config_version"] == 1


# ---- configuration change, staleness and recalculation -------------------------------------


def test_configuration_change_leaves_issues_stale_until_recalculated() -> None:
    admin = register_actor("admin@example.com")
    issue = make_issue(admin, make_category(admin))  # P3, 33.33
    assert put_config(admin, 0, **ONLY_NO_WORKAROUND).status_code == 200

    exp = explanation(admin, issue["id"])
    assert exp["stale"] is True
    assert exp["computed_priority"] == 1 and exp["effective_priority"] == 3
    assert exp["stored_score"] == pytest.approx(33.33) and exp["score"] == pytest.approx(100.0)
    assert admin.get(f"{issues_url(admin)}/{issue['id']}").json()["priority"] == 3  # untouched

    summary = admin.post(recalculate_url(admin)).json()
    assert summary == {"examined": 1, "priority_changed": 1, "overridden_skipped": 0}

    current = admin.get(f"{issues_url(admin)}/{issue['id']}").json()
    assert current["priority"] == 1 and current["version"] == 2
    assert current["priority_score"] == pytest.approx(100.0)
    assert explanation(admin, issue["id"])["stale"] is False

    changes = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()["changes"]
    assert [
        (c["field"], c["old_value"], c["new_value"], c["source"], c["actor_id"]) for c in changes
    ] == [("priority", 3, 1, "derived", admin.user_id)]


def test_recalculation_skips_closed_issues_and_keeps_manual_overrides() -> None:
    admin = register_actor("admin@example.com")
    category = make_category(admin)
    overridden = make_issue(
        admin, category, priority=4, priority_override_reason="Low business value"
    )
    closed = make_issue(admin, category, title="Already done")
    version = closed["version"]
    for status in ("resolved", "closed"):
        version = transition(admin, closed["id"], status, version).json()["version"]
    normal = make_issue(admin, category, title="Normal")
    assert put_config(admin, 0, **ONLY_NO_WORKAROUND).status_code == 200

    summary = admin.post(recalculate_url(admin)).json()
    assert summary == {"examined": 2, "priority_changed": 1, "overridden_skipped": 1}

    kept = admin.get(f"{issues_url(admin)}/{overridden['id']}").json()
    # Priority untouched, score refreshed, and a score-only refresh does not bump the version.
    assert kept["priority"] == 4 and kept["priority_score"] == pytest.approx(100.0)
    assert kept["version"] == 1
    untouched = admin.get(f"{issues_url(admin)}/{closed['id']}").json()
    assert untouched["priority"] == 3 and untouched["version"] == 3
    assert admin.get(f"{issues_url(admin)}/{normal['id']}").json()["priority"] == 1


def test_recalculation_requires_admin_and_stays_inside_the_workspace() -> None:
    alice, agent = register_actor("alice@example.com"), register_actor("agent@example.com")
    bob = register_actor("bob@example.com")
    add_member(alice, agent, "agent")
    bobs_issue = make_issue(bob, make_category(bob))
    assert put_config(bob, 0, **ONLY_NO_WORKAROUND).status_code == 200

    assert agent.post(recalculate_url(alice)).status_code == 403
    assert alice.post(recalculate_url(alice)).json()["examined"] == 0
    assert alice.post(recalculate_url(bob)).status_code == 404

    unchanged = bob.get(f"{issues_url(bob)}/{bobs_issue['id']}").json()
    assert unchanged["priority"] == 3 and unchanged["version"] == 1
