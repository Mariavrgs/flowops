from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import DbDep, WorkspaceContext, require_role
from app.api.schemas import MemberIn, MemberOut
from app.db.models import Membership, User
from app.domain.roles import Role
from app.services.auth import normalize_email

router = APIRouter(prefix="/workspaces/{workspace_id}/members", tags=["members"])

AdminDep = Annotated[WorkspaceContext, Depends(require_role(Role.ADMIN))]


@router.post("", status_code=201, response_model=MemberOut)
def add_member(body: MemberIn, ctx: AdminDep, db: DbDep) -> MemberOut:
    """Add an existing user to this workspace.

    Known limitation: answering 404 for an unknown email lets an admin probe which emails
    have accounts. An invitation flow would remove this; it is on the roadmap.
    """
    user = db.scalar(select(User).where(User.email == normalize_email(body.email)))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if db.get(Membership, (user.id, ctx.workspace_id)) is not None:
        raise HTTPException(status_code=409, detail="User is already a member")
    db.add(Membership(user_id=user.id, workspace_id=ctx.workspace_id, role=body.role.value))
    db.commit()
    return MemberOut(user_id=user.id, role=body.role)
