import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuthSession, Membership, User
from app.db.session import get_db
from app.domain.roles import Role
from app.security import hash_token

DbDep = Annotated[Session, Depends(get_db)]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def get_auth_context(request: Request, db: DbDep) -> AuthContext:
    """Authenticate the request from the session cookie and enforce CSRF on unsafe methods."""
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = db.get(AuthSession, hash_token(raw))
    if session is None or session.revoked_at is not None or session.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Not authenticated")

    if request.method not in SAFE_METHODS:
        sent = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")

    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return AuthContext(user=user, session=session)


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: uuid.UUID
    user: User
    role: Role


def get_workspace_context(workspace_id: uuid.UUID, auth: AuthDep, db: DbDep) -> WorkspaceContext:
    """Resolve the workspace in the URL for the current user.

    Not a member and does-not-exist both return the same 404, so the API never reveals
    whether a workspace (or anything inside it) exists.
    """
    membership = db.get(Membership, (auth.user.id, workspace_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceContext(workspace_id=workspace_id, user=auth.user, role=Role(membership.role))


WorkspaceDep = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require_role(*allowed: Role) -> Callable[[WorkspaceDep], WorkspaceContext]:
    """Dependency factory. 403 here is safe: the caller is already a member."""

    def dependency(ctx: WorkspaceDep) -> WorkspaceContext:
        if ctx.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return ctx

    return dependency
