import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Issue, IssueChange, IssueStatusEvent


def get(
    db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID, *, for_update: bool = False
) -> Issue | None:
    """`for_update=True` takes a row lock until the transaction ends."""
    stmt = select(Issue).where(Issue.workspace_id == workspace_id, Issue.id == issue_id)
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def list_for_workspace(db: Session, workspace_id: uuid.UUID, limit: int) -> Sequence[Issue]:
    """Temporary listing (newest first). Filters, sorting and keyset pagination: Delivery 6."""
    return db.scalars(
        select(Issue)
        .where(Issue.workspace_id == workspace_id)
        .order_by(Issue.created_at.desc(), Issue.id.desc())
        .limit(limit)
    ).all()


def fields_changed_since(
    db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID, version: int
) -> list[str]:
    return list(
        db.scalars(
            select(IssueChange.field)
            .where(
                IssueChange.workspace_id == workspace_id,
                IssueChange.issue_id == issue_id,
                IssueChange.version > version,
            )
            .distinct()
            .order_by(IssueChange.field)
        ).all()
    )


def list_changes(
    db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID
) -> Sequence[IssueChange]:
    return db.scalars(
        select(IssueChange)
        .where(IssueChange.workspace_id == workspace_id, IssueChange.issue_id == issue_id)
        .order_by(IssueChange.id)
    ).all()


def list_status_events(
    db: Session, workspace_id: uuid.UUID, issue_id: uuid.UUID
) -> Sequence[IssueStatusEvent]:
    return db.scalars(
        select(IssueStatusEvent)
        .where(IssueStatusEvent.workspace_id == workspace_id, IssueStatusEvent.issue_id == issue_id)
        .order_by(IssueStatusEvent.id)
    ).all()
