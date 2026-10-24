from itertools import product

import pytest

from app.domain.issue_state import (
    InvalidTransition,
    ReasonRequired,
    Status,
    allowed_transitions,
    is_reopen,
    validate_transition,
)

# Written independently of ALLOWED_TRANSITIONS on purpose: this is the specification,
# and the test checks that the table in the code matches it.
VALID = {
    (Status.OPEN, Status.IN_PROGRESS),
    (Status.OPEN, Status.BLOCKED),
    (Status.OPEN, Status.RESOLVED),
    (Status.IN_PROGRESS, Status.BLOCKED),
    (Status.IN_PROGRESS, Status.RESOLVED),
    (Status.BLOCKED, Status.IN_PROGRESS),
    (Status.RESOLVED, Status.CLOSED),
    (Status.RESOLVED, Status.OPEN),
}


def test_every_valid_transition_is_accepted() -> None:
    for current, target in VALID:
        validate_transition(current, target, "some reason")


def test_every_other_pair_is_rejected_and_lists_allowed_targets() -> None:
    for current, target in product(Status, Status):
        if (current, target) in VALID:
            continue
        with pytest.raises(InvalidTransition) as exc:
            validate_transition(current, target, "some reason")
        assert exc.value.allowed == allowed_transitions(current)


def test_blocking_requires_a_reason() -> None:
    for current in (Status.OPEN, Status.IN_PROGRESS):
        for reason in (None, "", "   "):
            with pytest.raises(ReasonRequired):
                validate_transition(current, Status.BLOCKED, reason)


def test_reopening_requires_a_reason() -> None:
    for reason in (None, "", "   "):
        with pytest.raises(ReasonRequired):
            validate_transition(Status.RESOLVED, Status.OPEN, reason)


def test_other_transitions_do_not_require_a_reason() -> None:
    validate_transition(Status.OPEN, Status.IN_PROGRESS, None)
    validate_transition(Status.IN_PROGRESS, Status.RESOLVED, None)
    validate_transition(Status.RESOLVED, Status.CLOSED, None)
    validate_transition(Status.BLOCKED, Status.IN_PROGRESS, None)


def test_closed_is_terminal() -> None:
    assert allowed_transitions(Status.CLOSED) == []


def test_only_resolved_to_open_is_a_reopen() -> None:
    reopens = [(c, t) for c, t in product(Status, Status) if is_reopen(c, t)]
    assert reopens == [(Status.RESOLVED, Status.OPEN)]


def test_validity_is_checked_before_reason() -> None:
    # closed -> blocked is invalid AND has no reason: the invalid transition is what is reported.
    with pytest.raises(InvalidTransition):
        validate_transition(Status.CLOSED, Status.BLOCKED, None)
