from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import AuthDep, DbDep
from app.api.schemas import LoginRequest, MembershipOut, RegisterRequest, SessionOut, UserOut
from app.config import settings
from app.db.models import AuthSession, Membership, User, Workspace
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,  # not readable from JavaScript
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _session_out(db: DbDep, user: User, session: AuthSession) -> SessionOut:
    rows = db.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.name)
    ).all()
    return SessionOut(
        user=UserOut.model_validate(user),
        memberships=[
            MembershipOut(workspace_id=w.id, workspace_name=w.name, role=m.role) for m, w in rows
        ],
        csrf_token=session.csrf_token,
    )


@router.post("/register", status_code=201, response_model=SessionOut)
def register(body: RegisterRequest, response: Response, db: DbDep) -> SessionOut:
    try:
        user, _workspace = auth_service.register(
            db,
            email=body.email,
            password=body.password,
            name=body.name,
            workspace_name=body.workspace_name,
        )
    except auth_service.EmailAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    raw, session = auth_service.create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw)
    return _session_out(db, user, session)


@router.post("/login", response_model=SessionOut)
def login(body: LoginRequest, response: Response, db: DbDep) -> SessionOut:
    user = auth_service.authenticate(db, email=body.email, password=body.password)
    if user is None:
        # Same message for unknown email and wrong password.
        raise HTTPException(status_code=401, detail="Invalid email or password")
    raw, session = auth_service.create_session(db, user)
    db.commit()
    _set_session_cookie(response, raw)
    return _session_out(db, user, session)


@router.get("/me", response_model=SessionOut)
def me(auth: AuthDep, db: DbDep) -> SessionOut:
    return _session_out(db, auth.user, auth.session)


@router.post("/logout", status_code=204)
def logout(auth: AuthDep, db: DbDep) -> Response:
    auth_service.revoke_session(db, auth.session)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response
