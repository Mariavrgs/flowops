"""The database must refuse bad data even if the application code is wrong.

These tests bypass the API and insert rows with raw SQL.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from tests.helpers import Actor, make_category, register_actor

pytestmark = pytest.mark.db

INSERT = text(
    """
    INSERT INTO issues (id, workspace_id, category_id, title, description, status, priority,
                        assignee_id, reporter_id, due_at)
    VALUES (:id, :ws, :cat, 't', '', :status, :priority, :assignee, :reporter, :due)
    """
)


def _params(owner: Actor, category_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ws": uuid.UUID(owner.workspace_id),
        "cat": uuid.UUID(category_id),
        "status": "open",
        "priority": 2,
        "assignee": None,
        "reporter": uuid.UUID(owner.user_id),
        "due": None,
    }
    base.update(overrides)
    return base


def _violated_constraint(params: dict[str, Any]) -> str | None:
    with SessionLocal() as db:
        with pytest.raises(IntegrityError) as exc:
            db.execute(INSERT, params)
            db.flush()
        db.rollback()
    diag = getattr(exc.value.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def test_baseline_insert_is_valid() -> None:
    alice = register_actor("alice@example.com")
    with SessionLocal() as db:
        db.execute(INSERT, _params(alice, make_category(alice)))
        db.commit()


def test_category_from_another_workspace_is_rejected() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    params = _params(alice, make_category(bob))
    assert _violated_constraint(params) == "fk_issues_category_same_workspace"


def test_assignee_outside_the_workspace_is_rejected() -> None:
    alice, bob = register_actor("alice@example.com"), register_actor("bob@example.com")
    params = _params(alice, make_category(alice), assignee=uuid.UUID(bob.user_id))
    assert _violated_constraint(params) == "fk_issues_assignee_is_member"


def test_due_date_before_creation_is_rejected() -> None:
    alice = register_actor("alice@example.com")
    params = _params(alice, make_category(alice), due=datetime(2000, 1, 1, tzinfo=UTC))
    assert _violated_constraint(params) == "ck_issues_due_after_created"


def test_invalid_status_and_priority_are_rejected() -> None:
    alice = register_actor("alice@example.com")
    category = make_category(alice)
    assert _violated_constraint(_params(alice, category, status="done")) == "ck_issues_status_valid"
    assert _violated_constraint(_params(alice, category, priority=9)) == "ck_issues_priority_range"
