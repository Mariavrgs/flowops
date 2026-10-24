import os

# Must run before the app is imported: settings (and the engine) read DATABASE_URL at import.
if _test_url := os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = _test_url

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.db.session import engine


@pytest.fixture(scope="session")
def _migrated_database() -> None:
    """Apply real migrations once per run (so migrations are exercised by the tests too).

    Safety: the suite truncates every table, so it refuses to touch a database whose name
    does not end with "_test". Run pytest from the backend/ directory (alembic.ini lookup).
    """
    name = engine.url.database or ""
    if not name.endswith("_test"):
        pytest.exit(
            f"Refusing to run DB tests against '{name}': the database name must end with "
            "'_test'. Set TEST_DATABASE_URL (see .env.example).",
            returncode=2,
        )
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def _clean_database(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.node.get_closest_marker("db") is None:
        yield
        return
    request.getfixturevalue("_migrated_database")
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield
