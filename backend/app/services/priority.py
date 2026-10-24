import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Issue, IssueChange, PriorityConfigRow
from app.domain.issue_state import Status
from app.domain.priority import (
    CriterionResult,
    PriorityConfig,
    PriorityInputs,
    PriorityResult,
    compute_priority,
)


class ConfigConflict(Exception):
    """The caller edited a stale configuration (same optimistic-lock idea as issues)."""

    def __init__(self, current: "ConfigState") -> None:
        super().__init__("Configuration was modified by someone else")
        self.current = current


@dataclass(frozen=True)
class ConfigState:
    config: PriorityConfig
    version: int  # 0 = defaults, nothing stored yet
    updated_at: datetime | None
    updated_by: uuid.UUID | None


def _config_from_row(row: PriorityConfigRow) -> PriorityConfig:
    return PriorityConfig(
        weight_impact=row.weight_impact,
        weight_urgency=row.weight_urgency,
        weight_affected_users=row.weight_affected_users,
        weight_no_workaround=row.weight_no_workaround,
        weight_deadline=row.weight_deadline,
        p1_min=row.p1_min,
        p2_min=row.p2_min,
        p3_min=row.p3_min,
    )


def get_config_state(
    db: Session, workspace_id: uuid.UUID, *, for_update: bool = False
) -> ConfigState:
    stmt = select(PriorityConfigRow).where(PriorityConfigRow.workspace_id == workspace_id)
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        return ConfigState(PriorityConfig(), 0, None, None)
    return ConfigState(_config_from_row(row), row.version, row.updated_at, row.updated_by)


def save_config(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    version: int,
    config: PriorityConfig,
    now: datetime | None = None,
) -> ConfigState:
    """Create or update the workspace configuration. `version` is what the caller last saw
    (0 if nothing was stored). Two admins creating the first row at the same time: the second
    insert violates the primary key and the route answers 409."""
    now = now or datetime.now(UTC)
    state = get_config_state(db, workspace_id, for_update=True)
    if state.version != version:
        raise ConfigConflict(state)
    values = {
        "weight_impact": config.weight_impact,
        "weight_urgency": config.weight_urgency,
        "weight_affected_users": config.weight_affected_users,
        "weight_no_workaround": config.weight_no_workaround,
        "weight_deadline": config.weight_deadline,
        "p1_min": config.p1_min,
        "p2_min": config.p2_min,
        "p3_min": config.p3_min,
        "version": state.version + 1,
        "updated_at": now,
        "updated_by": actor_id,
    }
    if state.version == 0:
        db.add(PriorityConfigRow(workspace_id=workspace_id, **values))
    else:
        row = db.get(PriorityConfigRow, workspace_id)
        assert row is not None
        for key, value in values.items():
            setattr(row, key, value)
    db.flush()
    return ConfigState(config, state.version + 1, now, actor_id)


def issue_inputs(issue: Issue) -> PriorityInputs:
    return PriorityInputs(
        impact=issue.impact,
        urgency=issue.urgency,
        affected_users=issue.affected_users,
        has_workaround=issue.has_workaround,
        due_at=issue.due_at,
        created_at=issue.created_at,
    )


@dataclass(frozen=True)
class Explanation:
    live: PriorityResult
    effective_priority: int
    overridden: bool
    override_reason: str | None
    stored_score: Decimal
    scored_at: datetime
    stale: bool
    config_version: int


def explain_issue(db: Session, issue: Issue, now: datetime | None = None) -> Explanation:
    """Score the issue NOW with the CURRENT configuration and compare with the stored snapshot."""
    now = now or datetime.now(UTC)
    state = get_config_state(db, issue.workspace_id)
    live = compute_priority(issue_inputs(issue), state.config, now)
    overridden = issue.priority_override_reason is not None
    stale = live.score != issue.priority_score or (
        not overridden and live.priority != issue.priority
    )
    return Explanation(
        live=live,
        effective_priority=issue.priority,
        overridden=overridden,
        override_reason=issue.priority_override_reason,
        stored_score=issue.priority_score,
        scored_at=issue.priority_scored_at,
        stale=stale,
        config_version=state.version,
    )


@dataclass(frozen=True)
class RecalcSummary:
    examined: int
    priority_changed: int
    overridden_skipped: int


def recalculate_workspace(
    db: Session, *, workspace_id: uuid.UUID, actor_id: uuid.UUID, now: datetime | None = None
) -> RecalcSummary:
    """Rescore every open (not closed) issue of the workspace with the current configuration.

    - The score snapshot is always refreshed.
    - The effective priority changes only for issues WITHOUT a manual override; those changes
      bump the issue version (visible change) and are logged as source="derived".
    - A score-only refresh does not bump the version.
    Rows are locked in id order so two concurrent recalculations cannot deadlock.
    """
    now = now or datetime.now(UTC)
    state = get_config_state(db, workspace_id)
    issues = db.scalars(
        select(Issue)
        .where(Issue.workspace_id == workspace_id, Issue.status != Status.CLOSED.value)
        .order_by(Issue.id)
        .with_for_update()
    ).all()
    changed = skipped = 0
    for issue in issues:
        result = compute_priority(issue_inputs(issue), state.config, now)
        issue.priority_score = result.score
        issue.priority_scored_at = now
        if issue.priority_override_reason is not None:
            skipped += 1
            continue
        if issue.priority != result.priority:
            old = issue.priority
            issue.priority = result.priority
            issue.version += 1
            issue.updated_at = now
            changed += 1
            db.add(
                IssueChange(
                    workspace_id=workspace_id,
                    issue_id=issue.id,
                    field="priority",
                    old_value=old,
                    new_value=result.priority,
                    actor_id=actor_id,
                    changed_at=now,
                    version=issue.version,
                    source="derived",
                )
            )
    db.flush()
    return RecalcSummary(examined=len(issues), priority_changed=changed, overridden_skipped=skipped)


def criterion_weight_percent(criterion: CriterionResult) -> Decimal:
    return criterion.weight_share * 100
