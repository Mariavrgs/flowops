# FlowOps

Incident, bug and request management for engineering teams, with transparent prioritization,
SLA tracking and an analytics dashboard.

> **Status:** Deliveries 0, 1, 2 and 4 implemented and passing the backend test suite (Delivery 3 pending). See [docs/BUSINESS_RULES.md](docs/BUSINESS_RULES.md) and [docs/PRIORITIZATION.md](docs/PRIORITIZATION.md).
> See [docs/ROADMAP.md](docs/ROADMAP.md) for the delivery plan.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · React + TypeScript + Vite · Pytest · Vitest ·
Docker Compose · GitHub Actions

## Run locally

```bash
cp .env.example .env        # then edit POSTGRES_PASSWORD
docker compose up --build
```

- Web: http://localhost:5173
- API docs: http://localhost:8000/api/docs
- Liveness: `GET /api/health` · Readiness (checks DB): `GET /api/health/db`

## Tests need a dedicated database

The suite truncates all tables, so it only runs against a database whose name ends in `_test`
(it exits otherwise). Compose creates `flowops_test` on first start. If your volume already
existed: `docker compose exec db createdb -U flowops flowops_test`.

```bash
docker compose exec api pytest          # TEST_DATABASE_URL is set by Compose
```

## Run the checks (without Docker)

```bash
# backend (needs a PostgreSQL reachable through DATABASE_URL for the `db` tests)
cd backend
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy
pytest -m "not db"          # no database needed
TEST_DATABASE_URL=postgresql+psycopg://flowops:<pw>@localhost:5432/flowops_test pytest   # full suite

# frontend
cd frontend
npm install
npm run lint && npm run typecheck && npm test
```

## Verification status

Evidence recorded so far (run by the project owner, output pasted in the project conversation):

| Check | Result | Environment |
|---|---|---|
| `docker compose up --build` | Images built; migrations 0001, 0002 and 0003 applied; API and Vite started | Docker Desktop on Windows, `python:3.12-slim`, PostgreSQL 16.15 |
| `docker compose exec api pytest` (full suite, includes database tests) | **106 passed**, 1 warning (Starlette/httpx deprecation) | same |
| `docker compose exec api alembic check` | No new upgrade operations detected (models and migrations agree) | same |
| Recorded on | 2026-10-24 | |

**Not verified yet:** `ruff` (format and lint), `mypy`, frontend checks (`eslint`, `tsc`, `vitest`,
`vite build`), the GitHub Actions workflow, and manual calls against the running API.

Note on concurrency tests: the threaded test asserts the invariant "exactly one winner" but cannot
prove the two requests overlapped; the deterministic stale-version test is the one that proves the rule.
