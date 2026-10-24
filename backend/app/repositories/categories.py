import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Category

# Rule for every repository function in this project: workspace_id is a REQUIRED argument
# and is part of every query. There is no way to fetch a workspace-owned row by id alone.


def list_for_workspace(db: Session, workspace_id: uuid.UUID) -> Sequence[Category]:
    return db.scalars(
        select(Category).where(Category.workspace_id == workspace_id).order_by(Category.name)
    ).all()


def get(db: Session, workspace_id: uuid.UUID, category_id: uuid.UUID) -> Category | None:
    return db.scalar(
        select(Category).where(Category.workspace_id == workspace_id, Category.id == category_id)
    )
