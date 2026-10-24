import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, WorkspaceContext, WorkspaceDep, require_role
from app.api.schemas import CategoryIn, CategoryOut
from app.db.models import Category
from app.domain.roles import Role
from app.repositories import categories as repo

router = APIRouter(prefix="/workspaces/{workspace_id}/categories", tags=["categories"])

AdminDep = Annotated[WorkspaceContext, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[CategoryOut])
def list_categories(ctx: WorkspaceDep, db: DbDep) -> Sequence[Category]:
    return repo.list_for_workspace(db, ctx.workspace_id)


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(category_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> Category:
    category = repo.get(db, ctx.workspace_id, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.post("", status_code=201, response_model=CategoryOut)
def create_category(body: CategoryIn, ctx: AdminDep, db: DbDep) -> Category:
    category = Category(workspace_id=ctx.workspace_id, name=body.name.strip(), kind=body.kind)
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_categories_workspace_name":
            raise HTTPException(status_code=409, detail="Category name already exists") from exc
        raise
    return category
