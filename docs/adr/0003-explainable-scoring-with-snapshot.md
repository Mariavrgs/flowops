# ADR 0003: Explainable weighted scoring, stored as a snapshot

- Status: accepted
- Date: 2026-10-23

## Context
Teams need to know *why* an issue has a given priority, and the rules must be testable. Part of
the score depends on time (deadline), so a stored value goes out of date.

## Decision
- A weighted sum of five bounded factors, exact arithmetic, configurable weights and thresholds
  per workspace. No learned model.
- Store the inputs, the score and when it was computed on the issue; compute the explanation
  **live** on request and flag `stale` when it differs from the snapshot.
- Manual overrides are allowed only with a written reason and are audited.

## Alternatives considered
- **Compute on every read, store nothing:** always fresh, but the server cannot filter or sort
  by priority in SQL (Delivery 6) without computing it for every row.
- **Store a breakdown JSON per issue:** duplicates data derivable from the inputs and goes stale
  in confusing ways when the configuration changes.
- **ML-based ranking:** not explainable, not reproducible in tests, and there is no real data.
- **Recompute automatically on every configuration change:** silently rewrites priorities people
  are working with; an explicit, audited recalculation is safer.

## Consequences
- Sorting and filtering by priority are cheap and indexable.
- A stored priority can lag behind the live computation; the API says so instead of hiding it.
- A scheduled recalculation job is needed to remove the lag (roadmap).
