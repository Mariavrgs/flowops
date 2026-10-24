# Prioritization

Priority is **derived from explicit criteria**, not guessed by a model. The rules live in
`backend/app/domain/priority.py` (pure code), are unit-tested, and every score can be explained
with `GET /api/workspaces/{ws}/issues/{id}/priority`.

## Formula

```
score    = sum over the 5 criteria of  100 × (weight_i / sum of weights) × factor_i      (0 to 100)
priority = P1 if score ≥ p1_min · P2 if ≥ p2_min · P3 if ≥ p3_min · otherwise P4
```

Defaults: weights 30 / 25 / 20 / 15 / 10 and thresholds 75 / 50 / 25. Weights are relative, so
only their proportions matter; a weight of 0 disables a criterion.

| Criterion | Input | Factor (0 to 1) |
|---|---|---|
| Impact | 1 to 4 | (n − 1) / 3 |
| Urgency | 1 to 4 | (n − 1) / 3 |
| Affected users | count ≥ 0 | 0–1 → 0 · 2–10 → 0.25 · 11–100 → 0.5 · 101–1000 → 0.75 · more than 1000 → 1 |
| No temporary workaround | yes/no | no workaround → 1 · workaround exists → 0.3 |
| Deadline proximity | `due_at` | share of the window `created_at → due_at` already used; no due date → 0; overdue or zero-length window → 1 |

## Rounding and explanations

Each criterion's points are rounded to 2 decimals (half up) and **the score is the sum of the
displayed points**, so an explanation always adds up. Calculations use `Decimal`, not `float`.

## Manual override

A person can set the priority by hand by sending `priority` **and** a non-blank
`priority_override_reason`. While an override exists:

- the effective priority does not change when inputs change;
- the score is still recomputed, so the explanation shows "computed P3, overridden to P1";
- the override and its reason are in the change history (`source = "user"`).

Sending `priority_override_reason: null` removes the override; the priority returns to the
computed one and that move is logged with `source = "derived"`.

## Why a stored score can be "stale"

The score depends on two things that change without anyone editing the issue:

1. **Time**: deadline proximity grows as the due date approaches.
2. **Configuration**: an admin may change weights or thresholds.

Therefore the issue stores a **snapshot** (`priority_score`, `priority_scored_at`) and the
explanation endpoint recomputes **live** and reports `stale: true` when they differ.

The snapshot is refreshed when an input is edited and when an admin calls
`POST /api/workspaces/{ws}/priority/recalculate`. Changing the configuration does **not**
rescore existing issues by itself, which mirrors the planned SLA-policy rule (Delivery 5): a
policy change must never silently rewrite existing work.

Recalculation rules: closed issues are skipped; overridden issues get a fresh score but keep
their priority; a priority move bumps the issue version (a stale editor gets a 409) and is
logged as `source = "derived"`, with the admin who ran it as actor; a score-only refresh does not
bump the version.

## Known limitations

- Nothing recalculates automatically as time passes. Until a scheduled job exists (roadmap),
  deadline-driven priority moves happen on edit or on an admin's recalculation.
- Recalculation loads and locks all open issues of a workspace in one transaction. Fine at the
  current scale; Delivery 10 will measure it.
- Configuration changes are versioned but there is no history of previous versions yet.
- The weights have no empirical basis: they are defaults a team is expected to tune.
