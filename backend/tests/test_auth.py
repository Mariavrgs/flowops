from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.config import settings
from app.db.models import AuthSession, Membership, User
from app.db.session import SessionLocal
from app.main import app
from app.security import hash_token
from tests.helpers import PASSWORD, register_actor

pytestmark = pytest.mark.db


def test_register_creates_user_workspace_and_admin_membership() -> None:
    actor = register_actor("ana@example.com", "Ana Team")
    me = actor.get("/api/auth/me").json()
    assert me["user"]["email"] == "ana@example.com"
    assert [(m["workspace_name"], m["role"]) for m in me["memberships"]] == [("Ana Team", "admin")]


def test_session_cookie_is_httponly_and_samesite_lax() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={"email": "a@example.com", "password": PASSWORD, "name": "A", "workspace_name": "W"},
    )
    cookie = response.headers["set-cookie"].lower()
    assert settings.session_cookie_name in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_password_is_hashed_with_argon2id_and_session_token_is_stored_hashed() -> None:
    actor = register_actor("hash@example.com")
    raw = actor.client.cookies.get(settings.session_cookie_name)
    assert raw is not None
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "hash@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert db.get(AuthSession, raw) is None  # raw token is never stored
        assert db.get(AuthSession, hash_token(raw)) is not None


def test_duplicate_email_is_rejected_case_insensitively() -> None:
    register_actor("dup@example.com")
    response = TestClient(app).post(
        "/api/auth/register",
        json={"email": "DUP@Example.com", "password": PASSWORD, "name": "X", "workspace_name": "W"},
    )
    assert response.status_code == 409


def test_register_rejects_short_password() -> None:
    response = TestClient(app).post(
        "/api/auth/register",
        json={"email": "s@example.com", "password": "short", "name": "S", "workspace_name": "W"},
    )
    assert response.status_code == 422


def test_failed_registration_leaves_no_partial_rows() -> None:
    register_actor("atomic@example.com")
    TestClient(app).post(
        "/api/auth/register",
        json={
            "email": "atomic@example.com",
            "password": PASSWORD,
            "name": "X",
            "workspace_name": "Second",
        },
    )
    with SessionLocal() as db:
        assert len(db.scalars(select(Membership)).all()) == 1


def test_login_success_and_uniform_failure() -> None:
    register_actor("login@example.com")
    ok = TestClient(app).post(
        "/api/auth/login", json={"email": "login@example.com", "password": PASSWORD}
    )
    assert ok.status_code == 200 and ok.json()["csrf_token"]

    wrong_pw = TestClient(app).post(
        "/api/auth/login", json={"email": "login@example.com", "password": "x" * 12}
    )
    unknown = TestClient(app).post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_me_requires_authentication() -> None:
    assert TestClient(app).get("/api/auth/me").status_code == 401


def test_logout_revokes_session_on_the_server() -> None:
    actor = register_actor("out@example.com")
    raw = actor.client.cookies.get(settings.session_cookie_name)
    assert actor.post("/api/auth/logout").status_code == 204
    # Replaying the old cookie by hand must fail: revocation is server-side, not just cookie deletion.
    replay = TestClient(app).get(
        "/api/auth/me", headers={"Cookie": f"{settings.session_cookie_name}={raw}"}
    )
    assert replay.status_code == 401


def test_expired_session_is_rejected() -> None:
    actor = register_actor("exp@example.com")
    with SessionLocal() as db:
        db.execute(update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    assert actor.get("/api/auth/me").status_code == 401


def test_state_changing_request_requires_valid_csrf_token() -> None:
    actor = register_actor("csrf@example.com")
    url = f"/api/workspaces/{actor.workspace_id}/categories"
    body = {"name": "Payments", "kind": "bug"}
    assert actor.client.post(url, json=body).status_code == 403
    assert actor.client.post(url, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert actor.post(url, body).status_code == 201
