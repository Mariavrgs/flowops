import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import DbDep, WorkspaceContext, WorkspaceDep, require_role
from app.api.schemas import (
    ChangeOut,
    CriterionOut,
    HistoryOut,
    IssueCreate,
    IssueOut,
    IssueUpdate,
    PriorityExplanationOut,
    StatusEventOut,
    TransitionIn,
)
from app.db.models import Issue
from app.domain.issue_state import InvalidTransition, ReasonRequired
from app.domain.roles import Role
from app.repositories import issues as repo
from app.services import issues as service
from app.services import priority as priority_service

router = APIRouter(prefix="/workspaces/{workspace_id}/issues", tags=["issues"])

# Admins and agents may write; viewers are read-only. Reopening is a write, so it is covered too.
WriterDep = Annotated[WorkspaceContext, Depends(require_role(Role.ADMIN, Role.AGENT))]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Issue not found")


def _conflict(exc: service.VersionConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "message": "Issue was modified by someone else. Review the current state and retry.",
            "current": IssueOut.model_validate(exc.current).model_dump(mode="json"),
            "changed_fields": exc.changed_fields,
        },
    )


@router.post("", status_code=201, response_model=IssueOut)
def create_issue(body: IssueCreate, ctx: WriterDep, db: DbDep) -> Issue:
    try:
        issue = service.create_issue(
            db,
            workspace_id=ctx.workspace_id,
            reporter_id=ctx.user.id,
            title=body.title,
            description=body.description,
            category_id=body.category_id,
            impact=body.impact,
            urgency=body.urgency,
            affected_users=body.affected_users,
            has_workaround=body.has_workaround,
            assignee_id=body.assignee_id,
            due_at=body.due_at,
            priority_override=body.priority,
            priority_override_reason=body.priority_override_reason,
        )
    except (service.InvalidReference, service.InvalidDueDate) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return issue


@router.get("", response_model=list[IssueOut])
def list_issues(
    ctx: WorkspaceDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> Sequence[Issue]:
    return repo.list_for_workspace(db, ctx.workspace_id, limit)


@router.get("/{issue_id}", response_model=IssueOut)
def get_issue(issue_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> Issue:
    issue = repo.get(db, ctx.workspace_id, issue_id)
    if issue is None:
        raise _not_found()
    return issue


@router.patch("/{issue_id}", response_model=IssueOut)
def update_issue(issue_id: uuid.UUID, body: IssueUpdate, ctx: WriterDep, db: DbDep) -> Issue:
    changes: dict[str, Any] = body.model_dump(exclude_unset=True, exclude={"version"})
    try:
        issue = service.update_issue(
            db,
            workspace_id=ctx.workspace_id,
            issue_id=issue_id,
            actor_id=ctx.user.id,
            version=body.version,
            changes=changes,
        )
    except service.IssueNotFound as exc:
        raise _not_found() from exc
    except service.VersionConflict as exc:
        raise _conflict(exc) from exc
    except (service.InvalidReference, service.InvalidDueDate, service.IssueClosed) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return issue


@router.post("/{issue_id}/transitions", response_model=IssueOut)
def transition_issue(issue_id: uuid.UUID, body: TransitionIn, ctx: WriterDep, db: DbDep) -> Issue:
    try:
        issue = service.transition_issue(
            db,
            workspace_id=ctx.workspace_id,
            issue_id=issue_id,
            actor_id=ctx.user.id,
            version=body.version,
            to_status=body.to_status,
            reason=body.reason,
        )
    except service.IssueNotFound as exc:
        raise _not_found() from exc
    except service.VersionConflict as exc:
        raise _conflict(exc) from exc
    except InvalidTransition as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "current_status": exc.current.value,
                "allowed_transitions": [s.value for s in exc.allowed],
            },
        ) from exc
    except ReasonRequired as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return issue


@router.get("/{issue_id}/history", response_model=HistoryOut)
def issue_history(issue_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> HistoryOut:
    if repo.get(db, ctx.workspace_id, issue_id) is None:
        raise _not_found()
    return HistoryOut(
        changes=[
            ChangeOut.model_validate(c) for c in repo.list_changes(db, ctx.workspace_id, issue_id)
        ],
        status_events=[
            StatusEventOut.model_validate(e)
            for e in repo.list_status_events(db, ctx.workspace_id, issue_id)
        ],
    )


@router.get("/{issue_id}/priority", response_model=PriorityExplanationOut)
def explain_priority(issue_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> PriorityExplanationOut:
    """Explain the priority: each criterion with its input, factor, weight and points."""
    issue = repo.get(db, ctx.workspace_id, issue_id)
    if issue is None:
        raise _not_found()
    explanation = priority_service.explain_issue(db, issue)
    return PriorityExplanationOut(
        score=explanation.live.score,
        computed_priority=explanation.live.priority,
        effective_priority=explanation.effective_priority,
        overridden=explanation.overridden,
        override_reason=explanation.override_reason,
        stored_score=explanation.stored_score,
        scored_at=explanation.scored_at,
        stale=explanation.stale,
        config_version=explanation.config_version,
        criteria=[
            CriterionOut(
                key=c.key,
                label=c.label,
                value=c.value,
                factor=c.factor,
                weight_percent=priority_service.criterion_weight_percent(c),
                points=c.points,
                explanation=c.explanation,
            )
            for c in explanation.live.criteria
        ],
        summary=explanation.live.summary,
    )
