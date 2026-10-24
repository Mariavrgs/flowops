from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.priority import (
    InvalidPriorityInput,
    PriorityConfig,
    PriorityInputs,
    affected_users_factor,
    compute_priority,
    deadline_factor,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _inputs(**overrides: object) -> PriorityInputs:
    base: dict[str, object] = {
        "impact": 2,
        "urgency": 2,
        "affected_users": 1,
        "has_workaround": False,
        "due_at": None,
        "created_at": T0,
    }
    base.update(overrides)
    return PriorityInputs(**base)  # type: ignore[arg-type]


def _only(**weights: int) -> PriorityConfig:
    """A config where only the named criteria have weight."""
    zero = {
        "weight_impact": 0,
        "weight_urgency": 0,
        "weight_affected_users": 0,
        "weight_no_workaround": 0,
        "weight_deadline": 0,
    }
    return PriorityConfig(**{**zero, **weights})


def test_default_inputs_with_default_config() -> None:
    result = compute_priority(_inputs(), PriorityConfig(), T0)
    # impact 2 -> 1/3 * 30 = 10.00 ; urgency 2 -> 1/3 * 25 = 8.33 ; users 1 -> 0 ;
    # no workaround -> 15.00 ; no due date -> 0
    assert [str(c.points) for c in result.criteria] == ["10.00", "8.33", "0.00", "15.00", "0.00"]
    assert result.score == Decimal("33.33")
    assert result.priority == 3


def test_maximum_inputs_give_100_and_p1() -> None:
    inputs = _inputs(impact=4, urgency=4, affected_users=5000, due_at=T0 + timedelta(hours=1))
    result = compute_priority(inputs, PriorityConfig(), T0 + timedelta(hours=2))  # overdue
    assert result.score == Decimal("100.00")
    assert result.priority == 1


def test_minimum_inputs_with_workaround() -> None:
    result = compute_priority(
        _inputs(impact=1, urgency=1, affected_users=0, has_workaround=True), PriorityConfig(), T0
    )
    assert result.score == Decimal("4.50")  # only the 0.3 workaround factor * 15
    assert result.priority == 4


def test_band_boundaries_are_inclusive_at_the_lower_edge() -> None:
    # Exactly 75, 50 and 25 points, built from a single criterion each time.
    p1 = compute_priority(
        _inputs(impact=4, urgency=1), _only(weight_impact=3, weight_urgency=1), T0
    )
    p2 = compute_priority(
        _inputs(impact=4, urgency=1), _only(weight_impact=1, weight_urgency=1), T0
    )
    p3 = compute_priority(
        _inputs(impact=4, urgency=1), _only(weight_impact=1, weight_urgency=3), T0
    )
    assert (p1.score, p1.priority) == (Decimal("75.00"), 1)
    assert (p2.score, p2.priority) == (Decimal("50.00"), 2)
    assert (p3.score, p3.priority) == (Decimal("25.00"), 3)
    just_below = compute_priority(_inputs(impact=3, urgency=1), _only(weight_impact=1), T0)
    assert just_below.score == Decimal("66.67") and just_below.priority == 2


def test_affected_users_bands() -> None:
    expected = {
        0: "0",
        1: "0",
        2: "0.25",
        10: "0.25",
        11: "0.5",
        100: "0.5",
        101: "0.75",
        1000: "0.75",
        1001: "1",
    }
    for users, factor in expected.items():
        assert affected_users_factor(users) == Decimal(factor), users


def test_deadline_factor() -> None:
    due = T0 + timedelta(hours=10)
    assert deadline_factor(None, T0, T0) == 0
    assert deadline_factor(due, T0, T0) == 0
    assert deadline_factor(due, T0, T0 + timedelta(hours=5)) == Decimal("0.5")
    assert deadline_factor(due, T0, due) == 1
    assert deadline_factor(due, T0, due + timedelta(days=3)) == 1
    assert deadline_factor(due, T0, T0 - timedelta(hours=1)) == 0  # clock before creation
    assert deadline_factor(T0, T0, T0 - timedelta(hours=1)) == 1  # zero-length window


def test_score_grows_as_the_deadline_approaches() -> None:
    inputs = _inputs(due_at=T0 + timedelta(hours=10))
    scores = [
        compute_priority(inputs, PriorityConfig(), T0 + timedelta(hours=h)).score
        for h in range(0, 11)
    ]
    assert scores == sorted(scores)
    assert scores[-1] - scores[0] == Decimal("10.00")  # deadline weight is 10 of 100


def test_weights_are_relative() -> None:
    a = compute_priority(_inputs(impact=4), _only(weight_impact=3, weight_urgency=3), T0)
    b = compute_priority(_inputs(impact=4), _only(weight_impact=1, weight_urgency=1), T0)
    assert a.score == b.score


def test_explanation_adds_up_and_names_the_band() -> None:
    result = compute_priority(_inputs(impact=4, urgency=3), PriorityConfig(), T0)
    assert [c.key for c in result.criteria] == [
        "impact",
        "urgency",
        "affected_users",
        "no_workaround",
        "deadline",
    ]
    assert sum(c.points for c in result.criteria) == result.score
    assert f"P{result.priority}" in result.summary
    assert "Impact" in result.summary  # a main contributor is named


def test_invalid_configuration_is_rejected() -> None:
    with pytest.raises(InvalidPriorityInput):
        _only()  # every weight zero
    with pytest.raises(InvalidPriorityInput):
        PriorityConfig(weight_impact=-1)
    with pytest.raises(InvalidPriorityInput):
        PriorityConfig(p1_min=50, p2_min=50)
    with pytest.raises(InvalidPriorityInput):
        PriorityConfig(p1_min=101)
    with pytest.raises(InvalidPriorityInput):
        PriorityConfig(p3_min=0)


def test_invalid_inputs_are_rejected() -> None:
    for bad in (
        {"impact": 0},
        {"impact": 5},
        {"urgency": 0},
        {"urgency": 5},
        {"affected_users": -1},
    ):
        with pytest.raises(InvalidPriorityInput):
            _inputs(**bad)
