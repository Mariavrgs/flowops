"""Transparent priority scoring. Pure functions: no database, no clock (the caller passes `now`).

    score    = sum over criteria of  100 * (weight_i / sum(weights)) * factor_i      (0..100)
    priority = P1 if score >= p1_min, else P2 if >= p2_min, else P3 if >= p3_min, else P4

Every factor is in [0, 1]. Money is not involved, so Decimal is used only to keep results exact
and reproducible (no float rounding surprises). Points are rounded to 2 decimals (half up) and
the score is the SUM OF THE DISPLAYED POINTS, so an explanation always adds up.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")
HUNDRED = Decimal(100)
WORKAROUND_FACTOR = Decimal("0.3")  # an existing workaround lowers urgency but never to zero


class InvalidPriorityInput(ValueError):
    """Invalid scoring inputs or configuration."""


@dataclass(frozen=True)
class PriorityConfig:
    """Weights are relative (they are normalized by their sum), so 30/25/20/15/10 and
    3/2.5/2/1.5/1 behave identically. A weight of 0 disables a criterion."""

    weight_impact: int = 30
    weight_urgency: int = 25
    weight_affected_users: int = 20
    weight_no_workaround: int = 15
    weight_deadline: int = 10
    p1_min: int = 75
    p2_min: int = 50
    p3_min: int = 25

    def __post_init__(self) -> None:
        weights = self.weights()
        if any(w < 0 for w in weights):
            raise InvalidPriorityInput("Weights must not be negative")
        if sum(weights) == 0:
            raise InvalidPriorityInput("At least one weight must be greater than zero")
        if not (100 >= self.p1_min > self.p2_min > self.p3_min >= 1):
            raise InvalidPriorityInput(
                "Thresholds must satisfy 100 >= p1_min > p2_min > p3_min >= 1"
            )

    def weights(self) -> tuple[int, int, int, int, int]:
        return (
            self.weight_impact,
            self.weight_urgency,
            self.weight_affected_users,
            self.weight_no_workaround,
            self.weight_deadline,
        )


@dataclass(frozen=True)
class PriorityInputs:
    impact: int  # 1 (minor) .. 4 (severe)
    urgency: int  # 1 (can wait) .. 4 (immediate)
    affected_users: int  # >= 0
    has_workaround: bool
    due_at: datetime | None
    created_at: datetime

    def __post_init__(self) -> None:
        if not 1 <= self.impact <= 4:
            raise InvalidPriorityInput("impact must be between 1 and 4")
        if not 1 <= self.urgency <= 4:
            raise InvalidPriorityInput("urgency must be between 1 and 4")
        if self.affected_users < 0:
            raise InvalidPriorityInput("affected_users must not be negative")


@dataclass(frozen=True)
class CriterionResult:
    key: str
    label: str
    value: str  # the input, in words
    factor: Decimal  # 0..1
    weight_share: Decimal  # this criterion's share of the total weight, 0..1
    points: Decimal  # contribution to the score
    explanation: str


@dataclass(frozen=True)
class PriorityResult:
    score: Decimal
    priority: int
    criteria: tuple[CriterionResult, ...]
    summary: str


# ---- factors -------------------------------------------------------------------------------


def impact_factor(impact: int) -> Decimal:
    return Decimal(impact - 1) / Decimal(3)


def urgency_factor(urgency: int) -> Decimal:
    return Decimal(urgency - 1) / Decimal(3)


def affected_users_factor(users: int) -> Decimal:
    """Logarithmic bands: 0-1 -> 0, 2-10 -> .25, 11-100 -> .5, 101-1000 -> .75, > 1000 -> 1."""
    if users <= 1:
        return Decimal(0)
    if users <= 10:
        return Decimal("0.25")
    if users <= 100:
        return Decimal("0.5")
    if users <= 1000:
        return Decimal("0.75")
    return Decimal(1)


def no_workaround_factor(has_workaround: bool) -> Decimal:
    return WORKAROUND_FACTOR if has_workaround else Decimal(1)


def deadline_factor(due_at: datetime | None, created_at: datetime, now: datetime) -> Decimal:
    """How much of the window [created_at, due_at] has been used up.

    No due date -> 0 (nothing is pressing). Past due, or a zero-length window -> 1.
    This is the only criterion that changes as time passes without any edit.
    """
    if due_at is None:
        return Decimal(0)
    if now >= due_at:
        return Decimal(1)
    one_us = timedelta(microseconds=1)
    window = (due_at - created_at) // one_us
    if window <= 0:
        return Decimal(1)
    remaining = (due_at - now) // one_us
    factor = Decimal(1) - Decimal(remaining) / Decimal(window)
    return min(max(factor, Decimal(0)), Decimal(1))


# ---- scoring -------------------------------------------------------------------------------


def _deadline_label(inputs: PriorityInputs, now: datetime) -> str:
    if inputs.due_at is None:
        return "no due date"
    if now >= inputs.due_at:
        return "overdue"
    hours_left = (inputs.due_at - now).total_seconds() / 3600
    window = (inputs.due_at - inputs.created_at).total_seconds() / 3600
    return f"{hours_left:.1f}h left of a {window:.1f}h window"


def band_for(score: Decimal, config: PriorityConfig) -> int:
    if score >= config.p1_min:
        return 1
    if score >= config.p2_min:
        return 2
    if score >= config.p3_min:
        return 3
    return 4


def compute_priority(
    inputs: PriorityInputs, config: PriorityConfig, now: datetime
) -> PriorityResult:
    total = Decimal(sum(config.weights()))
    specs = (
        (
            "impact",
            "Impact",
            f"{inputs.impact} of 4",
            impact_factor(inputs.impact),
            config.weight_impact,
        ),
        (
            "urgency",
            "Urgency",
            f"{inputs.urgency} of 4",
            urgency_factor(inputs.urgency),
            config.weight_urgency,
        ),
        (
            "affected_users",
            "Affected users",
            str(inputs.affected_users),
            affected_users_factor(inputs.affected_users),
            config.weight_affected_users,
        ),
        (
            "no_workaround",
            "No temporary workaround",
            "a workaround exists" if inputs.has_workaround else "no workaround",
            no_workaround_factor(inputs.has_workaround),
            config.weight_no_workaround,
        ),
        (
            "deadline",
            "Deadline proximity",
            _deadline_label(inputs, now),
            deadline_factor(inputs.due_at, inputs.created_at, now),
            config.weight_deadline,
        ),
    )
    criteria: list[CriterionResult] = []
    for key, label, value, factor, weight in specs:
        share = Decimal(weight) / total
        points = (HUNDRED * share * factor).quantize(TWO_PLACES, ROUND_HALF_UP)
        criteria.append(
            CriterionResult(
                key=key,
                label=label,
                value=value,
                factor=factor,
                weight_share=share,
                points=points,
                explanation=(
                    f"{label}: {value} -> factor {factor:.2f} x weight {share * 100:.1f}% "
                    f"= {points} points"
                ),
            )
        )

    score = min(max(sum((c.points for c in criteria), Decimal(0)), Decimal(0)), HUNDRED)
    priority = band_for(score, config)
    bands = {
        1: f"P1 (score >= {config.p1_min})",
        2: f"P2 (score >= {config.p2_min} and < {config.p1_min})",
        3: f"P3 (score >= {config.p3_min} and < {config.p2_min})",
        4: f"P4 (score < {config.p3_min})",
    }
    top = [c for c in sorted(criteria, key=lambda c: c.points, reverse=True)[:2] if c.points > 0]
    contributors = (
        "Main contributors: " + ", ".join(f"{c.label} (+{c.points})" for c in top) + "."
        if top
        else "No criterion contributes points."
    )
    return PriorityResult(
        score=score,
        priority=priority,
        criteria=tuple(criteria),
        summary=f"Score {score} places this issue in {bands[priority]}. {contributors}",
    )
