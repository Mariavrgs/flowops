# Business rules

Rules are implemented in `backend/app/domain/` (pure code) and enforced in `backend/app/services/`.
Each rule below names the test that covers it.

## Issue lifecycle (state machine)

| From | Allowed targets | Notes |
|---|---|---|
| open | in_progress, blocked, resolved | blocking needs a reason |
| in_progress | blocked, resolved | blocking needs a reason |
| blocked | in_progress | must go back to in_progress before it can be resolved |
| resolved | closed, open | `resolved → open` is a **reopen**: reason required, `reopen_count + 1` |
| closed | none | terminal; closed issues are read-only. To continue the work, create a new issue. |

Invalid transition → `422` listing `allowed_transitions`. Missing reason → `422`.
Tests: `tests/test_issue_state.py` (rules), `tests/test_issue_transitions.py` (through the API).

## Concurrent edits (optimistic locking)

- Every issue has a `version`, starting at 1, incremented by each successful change.
- `PATCH` and `POST .../transitions` must send the `version` the client last saw.
- The server locks the row (`SELECT ... FOR UPDATE`), then compares versions.
  - Equal: the change is applied and the version is incremented.
  - Different: **`409 Conflict`**, nothing is applied. The body contains the current issue and
    `changed_fields`, the fields changed by others since the client's version.
- The client decides what to do (typically: show the differences, retry with the new version).
- Order of checks: not found (404) → stale version (409) → closed / invalid transition / invalid
  data (422). A stale client therefore always learns about the conflict first.
- A `PATCH` that changes nothing succeeds and does **not** bump the version.
- Tests: `tests/test_concurrency.py`.

## Two histories, two purposes

- `issue_status_events`: append-only timeline of status changes (with the reason). It is the
  **only** input for SLA and resolution-time calculations (Deliveries 5 and 8).
- `issue_changes`: audit log shown to humans, one row per changed field (including `status`),
  with old value, new value, actor and resulting version.

## Referential rules enforced by the database

See `tests/test_db_constraints.py`: category and assignee must belong to the issue's workspace,
due date cannot precede creation, status and priority are constrained.

## Priority

Derived from scoring inputs; see [PRIORITIZATION.md](PRIORITIZATION.md).
Tests: `tests/test_priority_domain.py` (rules), `tests/test_priority.py` (through the API).
