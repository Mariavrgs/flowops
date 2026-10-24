from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from tests.helpers import (
    Actor,
    add_member,
    issues_url,
    make_category,
    make_issue,
    patch,
    register_actor,
    transition,
)

pytestmark = pytest.mark.db


def test_stale_edit_returns_409_with_current_state_and_changed_fields() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    add_member(admin, agent, "agent")
    issue = make_issue(admin, make_category(admin))
    iid = issue["id"]

    # Both people loaded version 1. The admin saves first.
    assert patch(admin, iid, {"version": 1, "title": "Admin's title"}).status_code == 200

    # The agent, still holding version 1, tries to change another field.
    response = agent.client.patch(
        f"{issues_url(admin)}/{iid}",
        json={"version": 1, "urgency": 4},
        headers={"X-CSRF-Token": agent.csrf},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["changed_fields"] == ["title"]
    assert detail["current"]["version"] == 2
    assert detail["current"]["title"] == "Admin's title"

    # Nothing was applied silently.
    current = admin.get(f"{issues_url(admin)}/{iid}").json()
    assert current["urgency"] == 2 and current["version"] == 2

    # Retrying with the version from the conflict response works.
    retry = agent.client.patch(
        f"{issues_url(admin)}/{iid}",
        json={"version": 2, "urgency": 4},
        headers={"X-CSRF-Token": agent.csrf},
    )
    assert retry.status_code == 200 and retry.json()["version"] == 3


def test_stale_transition_returns_409() -> None:
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    add_member(admin, agent, "agent")
    issue = make_issue(admin, make_category(admin))
    assert transition(admin, issue["id"], "in_progress", 1).status_code == 200
    stale = agent.post(
        f"{issues_url(admin)}/{issue['id']}/transitions", {"to_status": "resolved", "version": 1}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["changed_fields"] == ["status"]


def test_simultaneous_transitions_from_the_same_version_have_exactly_one_winner() -> None:
    """Invariant check. It does not prove the requests overlapped in time (a barrier makes
    that likely, not certain), but whatever the interleaving, the invariant must hold."""
    admin, agent = register_actor("admin@example.com"), register_actor("agent@example.com")
    add_member(admin, agent, "agent")
    issue = make_issue(admin, make_category(admin))
    url = f"{issues_url(admin)}/{issue['id']}/transitions"
    barrier = Barrier(2)

    def go(actor: Actor, target: str) -> int:
        barrier.wait()
        return actor.client.post(
            url, json={"to_status": target, "version": 1}, headers={"X-CSRF-Token": actor.csrf}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(
            f.result()
            for f in [pool.submit(go, admin, "in_progress"), pool.submit(go, agent, "resolved")]
        )
    assert results == [200, 409]

    history = admin.get(f"{issues_url(admin)}/{issue['id']}/history").json()
    assert len(history["status_events"]) == 2  # the initial "open" + exactly one transition
    assert admin.get(f"{issues_url(admin)}/{issue['id']}").json()["version"] == 2
