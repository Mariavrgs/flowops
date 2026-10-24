from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, WorkspaceContext, WorkspaceDep, require_role
from app.api.schemas import PriorityConfigIn, PriorityConfigOut, RecalculateOut
from app.domain.priority import InvalidPriorityInput, PriorityConfig
from app.domain.roles import Role
from app.services import priority as service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["priority"])

AdminDep = Annotated[WorkspaceContext, Depends(require_role(Role.ADMIN))]


def _config_out(state: service.ConfigState) -> PriorityConfigOut:
    return PriorityConfigOut(
        **asdict(state.config),
        version=state.version,
        updated_at=state.updated_at,
        updated_by=state.updated_by,
    )


@router.get("/priority-config", response_model=PriorityConfigOut)
def get_priority_config(ctx: WorkspaceDep, db: DbDep) -> PriorityConfigOut:
    return _config_out(service.get_config_state(db, ctx.workspace_id))


@router.put("/priority-config", response_model=PriorityConfigOut)
def put_priority_config(body: PriorityConfigIn, ctx: AdminDep, db: DbDep) -> PriorityConfigOut:
    """Changing the configuration does NOT rescore existing issues by itself: issues keep their
    stored priority until they are edited or an admin calls /priority/recalculate."""
    try:
        config = PriorityConfig(**body.model_dump(exclude={"version"}))
    except InvalidPriorityInput as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        state = service.save_config(
            db,
            workspace_id=ctx.workspace_id,
            actor_id=ctx.user.id,
            version=body.version,
            config=config,
        )
        db.commit()
    except service.ConfigConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Configuration was modified by someone else. Review it and retry.",
                "current": _config_out(exc.current).model_dump(mode="json"),
            },
        ) from exc
    except IntegrityError as exc:  # two admins creating the first row at the same time
        db.rollback()
        raise HTTPException(
            status_code=409, detail={"message": "Configuration was modified by someone else."}
        ) from exc
    return _config_out(state)


@router.post("/priority/recalculate", response_model=RecalculateOut)
def recalculate(ctx: AdminDep, db: DbDep) -> RecalculateOut:
    summary = service.recalculate_workspace(db, workspace_id=ctx.workspace_id, actor_id=ctx.user.id)
    db.commit()
    return RecalculateOut(
        examined=summary.examined,
        priority_changed=summary.priority_changed,
        overridden_skipped=summary.overridden_skipped,
    )
