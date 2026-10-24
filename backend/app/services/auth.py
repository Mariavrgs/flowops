import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuthSession, Membership, User, Workspace
from app.domain.roles import Role
from app.security import (
    DUMMY_HASH,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)


class EmailAlreadyRegistered(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


def register(
    db: Session, *, email: str, password: str, name: str, workspace_name: str
) -> tuple[User, Workspace]:
    """Create a user and their first workspace (as admin) in one transaction.

    Uniqueness is enforced by the database constraint, not by a check-then-insert, so two
    simultaneous registrations with the same email cannot both succeed.
    """
    user = User(
        email=normalize_email(email), name=name.strip(), password_hash=hash_password(password)
    )
    workspace = Workspace(name=workspace_name.strip(), slug=_slugify(workspace_name))
    db.add_all([user, workspace])
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_users_email":
            raise EmailAlreadyRegistered from exc
        raise
    db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=Role.ADMIN.value))
    return user, workspace


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(DUMMY_HASH, password)
        return None
    return user if verify_password(user.password_hash, password) else None


def create_session(db: Session, user: User) -> tuple[str, AuthSession]:
    """Returns (raw cookie token, session row). Only the hash of the token is stored."""
    raw = new_token()
    now = datetime.now(UTC)
    session = AuthSession(
        id=hash_token(raw),
        user_id=user.id,
        csrf_token=new_token(),
        created_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    return raw, session


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = datetime.now(UTC)
    db.add(session)
