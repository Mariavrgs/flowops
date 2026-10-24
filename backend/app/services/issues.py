import uuid
from datetime import UTC, datetime
from typing import Any, NamedTuple

from sqlalchemy.orm import Session

from app.db.models import Issue, IssueChange, IssueStatusEvent, Membership
from app.domain.issue_state import Status, is_reopen, validate_transition
from app.domain.priority import compute_priority
from app.repositories import categories as categories_repo
from app.repositories import issues as repo
from app.services import priority as priority_service


class IssueNotFound(Exception):
    pass


class InvalidReference(Exception):
    """Category or assignee does not belong to this workspace."""


class InvalidDueDate(Exception):
    pass


class IssueClosed(Exception):
    """Closed is terminal: closed issues are read-only."""


class VersionConflict(Exception):
    """The caller edited a stale copy. Never resolved silently: the caller decides."""

    def __init__(self, current: Issue, changed_fields: list[str]) -> None:
        super().__init__("Issue was modified by someone else")
        self.current = current
        self.changed_fields = changed_fields


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _validate_references(
    db: Session,
    workspace_id: uuid.UUID,
    category_id: uuid.UUID | None,
    assignee_id: uuid.UUID | None,
) -> None:
    if category_id is not None and categories_repo.get(db, workspace_id, category_id) is None:
        raise InvalidReference("Category does not exist in this workspace")
    if assignee_id is not None and db.get(Membership, (assignee_id, workspace_id)) is None:
        raise InvalidReference("Assignee must be a member of this workspace")


def _get_locked_and_checked(
    db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID, version: int
) -> Issue:
    """Lock the row, then compare versions. The lock makes check-and-write atomic."""
    issue = repo.get(db, workspace_id, issue_id, for_update=True)
    if issue is None:
        raise IssueNotFound
    if issue.version != version:
        raise VersionConflict(issue, repo.fields_changed_since(db, workspace_id, issue_id, version))
    return issue


def create_issue(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    reporter_id: uuid.UUID,
    title: str,
    description: str,
    category_id: uuid.UUID,
    impact: int,
    urgency: int,
    affected_users: int,
    has_workaround: bool,
    assignee_id: uuid.UUID | None,
    due_at: datetime | None,
    priority_override: int | None = None,
    priority_override_reason: str | None = None,
    now: datetime | None = None,
) -> Issue:
    now = now or datetime.now(UTC)
    _validate_references(db, workspace_id, category_id, assignee_id)
    if due_at is not None and due_at < now:
        raise InvalidDueDate("Due date cannot be in the past")
    issue = Issue(
        workspace_id=workspace_id,
        category_id=category_id,
        title=title,
        description=description,
        status=Status.OPEN.value,
        impact=impact,
        urgency=urgency,
        affected_users=affected_users,
        has_workaround=has_workaround,
        assignee_id=assignee_id,
        reporter_id=reporter_id,
        due_at=due_at,
        created_at=now,
        updated_at=now,
        version=1,
        reopen_count=0,
    )
    state = priority_service.get_config_state(db, workspace_id)
    result = compute_priority(priority_service.issue_inputs(issue), state.config, now)
    issue.priority_score = result.score
    issue.priority_scored_at = now
    if priority_override is not None:
        issue.priority = priority_override
        issue.priority_override_reason = priority_override_reason
    else:
        issue.priority = result.priority
        issue.priority_override_reason = None
    db.add(issue)
    db.flush()
    # The first event has the same timestamp as created_at: the clock starts when the issue opens.
    db.add(
        IssueStatusEvent(
            workspace_id=workspace_id,
            issue_id=issue.id,
            from_status=None,
            to_status=Status.OPEN.value,
            actor_id=reporter_id,
            occurred_at=now,
            reason=None,
        )
    )
    db.flush()
    return issue


SCORE_INPUT_FIELDS = frozenset({"impact", "urgency", "affected_users", "has_workaround", "due_at"})
DIRECT_FIELDS = (
    frozenset({"title", "description", "category_id", "assignee_id"}) | SCORE_INPUT_FIELDS
)


class _Record(NamedTuple):
    field: str
    old: Any
    new: Any
    source: str  # "user" | "derived"


def update_issue(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    issue_id: uuid.UUID,
    actor_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
    now: datetime | None = None,
) -> Issue:
    """Apply a partial update. Only keys present in `changes` are touched.

    Priority is DERIVED from the scoring inputs. It can only be set by hand through the pair
    `priority` + `priority_override_reason`; `priority_override_reason: None` removes the override.
    Whenever an input changes, the score is recomputed (and the priority, unless overridden).

    Order of checks: not found -> stale version (409) -> closed -> references/dates (422).
    A request that changes nothing succeeds without bumping the version.
    """
    now = now or datetime.now(UTC)
    issue = _get_locked_and_checked(db, workspace_id, issue_id, version)
    if issue.status == Status.CLOSED.value:
        raise IssueClosed("Closed issues cannot be edited")

    _validate_references(db, workspace_id, changes.get("category_id"), changes.get("assignee_id"))
    new_due = changes.get("due_at")
    if new_due is not None and new_due < issue.created_at:
        raise InvalidDueDate("Due date cannot be before the issue was created")

    records: list[_Record] = []
    for field, new in changes.items():
        if field in DIRECT_FIELDS:
            old = getattr(issue, field)
            if old != new:
                records.append(_Record(field, old, new, "user"))
                setattr(issue, field, new)

    override_cleared = False
    if "priority_override_reason" in changes:
        reason = changes["priority_override_reason"]
        if reason is None:
            if issue.priority_override_reason is not None:
                records.append(
                    _Record(
                        "priority_override_reason", issue.priority_override_reason, None, "user"
                    )
                )
                issue.priority_override_reason = None
                override_cleared = True
        else:
            if issue.priority_override_reason != reason:
                records.append(
                    _Record(
                        "priority_override_reason", issue.priority_override_reason, reason, "user"
                    )
                )
                issue.priority_override_reason = reason
            new_priority = changes["priority"]
            if issue.priority != new_priority:
                records.append(_Record("priority", issue.priority, new_priority, "user"))
                issue.priority = new_priority

    if override_cleared or any(r.field in SCORE_INPUT_FIELDS for r in records):
        state = priority_service.get_config_state(db, workspace_id)
        result = compute_priority(priority_service.issue_inputs(issue), state.config, now)
        issue.priority_score = result.score
        issue.priority_scored_at = now
        if issue.priority_override_reason is None and issue.priority != result.priority:
            records.append(_Record("priority", issue.priority, result.priority, "derived"))
            issue.priority = result.priority

    if not records:
        return issue

    issue.version += 1
    issue.updated_at = now
    for record in records:
        db.add(
            IssueChange(
                workspace_id=workspace_id,
                issue_id=issue.id,
                field=record.field,
                old_value=_jsonable(record.old),
                new_value=_jsonable(record.new),
                actor_id=actor_id,
                changed_at=now,
                version=issue.version,
                source=record.source,
            )
        )
    db.flush()
    return issue


def transition_issue(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    issue_id: uuid.UUID,
    actor_id: uuid.UUID,
    version: int,
    to_status: Status,
    reason: str | None,
    now: datetime | None = None,
) -> Issue:
    """Move an issue to a new status, recording the event and the audit entry atomically.

    Raises InvalidTransition / ReasonRequired (see domain.issue_state) after the version check.
    """
    now = now or datetime.now(UTC)
    issue = _get_locked_and_checked(db, workspace_id, issue_id, version)
    current = Status(issue.status)
    reason = reason.strip() if reason and reason.strip() else None
    validate_transition(current, to_status, reason)

    issue.status = to_status.value
    issue.version += 1
    issue.updated_at = now
    if is_reopen(current, to_status):
        issue.reopen_count += 1
    db.add(
        IssueStatusEvent(
            workspace_id=workspace_id,
            issue_id=issue.id,
            from_status=current.value,
            to_status=to_status.value,
            actor_id=actor_id,
            occurred_at=now,
            reason=reason,
        )
    )
    db.add(
        IssueChange(
            workspace_id=workspace_id,
            issue_id=issue.id,
            field="status",
            old_value=current.value,
            new_value=to_status.value,
            actor_id=actor_id,
            changed_at=now,
            version=issue.version,
        )
    )
    db.flush()
    return issue
