import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_does_not_need_database() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.db
def test_readiness_with_database() -> None:
    response = client.get("/api/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
