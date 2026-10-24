"""Issue lifecycle rules. Pure functions: no database, no I/O.

    open ──▶ in_progress ◀──▶ blocked
      │          │
      └──────────┴──▶ resolved ──▶ closed (terminal)
                         │
                         └──▶ open   (reopen: reason required, reopen_count + 1)

Also allowed: open ──▶ blocked and open ──▶ resolved.
Not allowed: blocked ──▶ resolved (an unblocked issue goes back to in_progress first, so the
SLA clock is running again before the resolution is recorded), anything out of closed.
"""

from collections.abc import Mapping
from enum import StrEnum


class Status(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    CLOSED = "closed"


ALLOWED_TRANSITIONS: Mapping[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS, Status.BLOCKED, Status.RESOLVED}),
    Status.IN_PROGRESS: frozenset({Status.BLOCKED, Status.RESOLVED}),
    Status.BLOCKED: frozenset({Status.IN_PROGRESS}),
    Status.RESOLVED: frozenset({Status.CLOSED, Status.OPEN}),
    Status.CLOSED: frozenset(),
}


class DomainError(Exception):
    """Base class for business-rule violations."""


class InvalidTransition(DomainError):
    def __init__(self, current: Status, target: Status, allowed: list[Status]) -> None:
        super().__init__(f"Cannot move from '{current}' to '{target}'")
        self.current = current
        self.target = target
        self.allowed = allowed


class ReasonRequired(DomainError):
    def __init__(self, current: Status, target: Status) -> None:
        super().__init__(f"A reason is required to move from '{current}' to '{target}'")
        self.current = current
        self.target = target


def allowed_transitions(current: Status) -> list[Status]:
    """Targets reachable from `current`, in declaration order (stable for API clients)."""
    return [s for s in Status if s in ALLOWED_TRANSITIONS[current]]


def is_reopen(current: Status, target: Status) -> bool:
    return current is Status.RESOLVED and target is Status.OPEN


def reason_required(current: Status, target: Status) -> bool:
    return target is Status.BLOCKED or is_reopen(current, target)


def validate_transition(current: Status, target: Status, reason: str | None) -> None:
    """Raise if the transition is not allowed. Validity is checked before the reason."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(current, target, allowed_transitions(current))
    if reason_required(current, target) and not (reason and reason.strip()):
        raise ReasonRequired(current, target)
