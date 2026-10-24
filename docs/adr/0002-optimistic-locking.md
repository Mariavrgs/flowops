# ADR 0002: Optimistic locking with a version column

- Status: accepted
- Date: 2026-10-21

## Context
Two people can edit or transition the same issue at the same time. The requirement is that
conflicts are never resolved silently.

## Decision
A `version` integer on `issues`, checked on every write, plus a row lock (`FOR UPDATE`) held
while checking and writing. A stale version returns `409` with the current state and the fields
that changed.

## Alternatives considered
- **Last write wins:** simplest, but silently discards someone's work.
- **Pessimistic locks ("checked out" by a user):** locks are forgotten when people close the tab,
  and need expiry rules.
- **Timestamp as version (`updated_at`):** clocks and precision make equality checks fragile.
- **`UPDATE ... WHERE version = :v` and check the row count:** also correct and avoids an
  explicit lock; we chose lock-then-compare because it lets us read the current row and report
  which fields changed inside the same transaction.

## Consequences
- Clients must carry `version` through their forms.
- A lock is held only for the duration of one short request.
- Status transitions and edits share one counter, so a transition also invalidates stale edits.
