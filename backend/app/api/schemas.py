import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    StringConstraints,
    model_validator,
)

from app.domain.issue_state import Status
from app.domain.roles import Role


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    workspace_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    name: str


class MembershipOut(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    role: Role


class SessionOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    # Sent back in the X-CSRF-Token header on every state-changing request.
    csrf_token: str


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["bug", "incident", "request"]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    kind: str


class MemberIn(BaseModel):
    email: EmailStr
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    role: Role


# Decimals are exact inside the server but travel as plain JSON numbers.
Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=10_000)]
OverrideReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
Impact = Annotated[int, Field(ge=1, le=4)]
AffectedUsers = Annotated[int, Field(ge=0, le=100_000_000)]


class IssueCreate(BaseModel):
    title: Title
    description: Description = ""
    category_id: uuid.UUID
    impact: Impact = 2
    urgency: Impact = 2
    affected_users: AffectedUsers = 1
    has_workaround: bool = False
    assignee_id: uuid.UUID | None = None
    due_at: AwareDatetime | None = None
    # Optional manual override. Both fields or neither.
    priority: Annotated[int, Field(ge=1, le=4)] | None = None
    priority_override_reason: OverrideReason | None = None

    @model_validator(mode="after")
    def _override_is_a_pair(self) -> "IssueCreate":
        if (self.priority is None) != (self.priority_override_reason is None):
            raise ValueError("priority and priority_override_reason must be provided together")
        return self


class IssueUpdate(BaseModel):
    """Partial update. Omitted field = unchanged. `assignee_id: null` / `due_at: null` clear them.

    Priority is derived from impact, urgency, affected_users, has_workaround and due_at.
    To set it by hand send `priority` AND `priority_override_reason`.
    To go back to the computed priority send `priority_override_reason: null` (without priority).
    """

    version: int = Field(ge=1)
    title: Title | None = None
    description: Description | None = None
    category_id: uuid.UUID | None = None
    impact: Impact | None = None
    urgency: Impact | None = None
    affected_users: AffectedUsers | None = None
    has_workaround: bool | None = None
    assignee_id: uuid.UUID | None = None
    due_at: AwareDatetime | None = None
    priority: Annotated[int, Field(ge=1, le=4)] | None = None
    priority_override_reason: OverrideReason | None = None

    @model_validator(mode="after")
    def _validate(self) -> "IssueUpdate":
        sent = self.model_fields_set
        required = (
            "title", "description", "category_id", "impact", "urgency",
            "affected_users", "has_workaround", "priority",
        )  # fmt: skip
        for name in required:
            if name in sent and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        reason_sent = "priority_override_reason" in sent
        if "priority" in sent:
            if not reason_sent or self.priority_override_reason is None:
                raise ValueError("priority requires priority_override_reason")
        elif reason_sent and self.priority_override_reason is not None:
            raise ValueError("priority_override_reason requires priority")
        return self


class TransitionIn(BaseModel):
    to_status: Status
    version: int = Field(ge=1)
    reason: Annotated[str, StringConstraints(max_length=1000)] | None = None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str
    category_id: uuid.UUID
    status: str
    priority: int
    # null = the priority is the computed one; otherwise a person set it, for this reason
    priority_override_reason: str | None
    priority_score: Num
    priority_scored_at: datetime
    impact: int
    urgency: int
    affected_users: int
    has_workaround: bool
    assignee_id: uuid.UUID | None
    reporter_id: uuid.UUID
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    reopen_count: int


class ChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    field: str
    old_value: Any
    new_value: Any
    actor_id: uuid.UUID
    changed_at: datetime
    version: int
    source: str


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: str | None
    to_status: str
    actor_id: uuid.UUID
    occurred_at: datetime
    reason: str | None


class HistoryOut(BaseModel):
    changes: list[ChangeOut]
    status_events: list[StatusEventOut]


class CriterionOut(BaseModel):
    key: str
    label: str
    value: str
    factor: Num
    weight_percent: Num
    points: Num
    explanation: str


class PriorityExplanationOut(BaseModel):
    """Why the issue has its priority. `score`/`computed_priority` are live (now, current
    configuration); `stored_score` and `effective_priority` are what is saved on the issue."""

    score: Num
    computed_priority: int
    effective_priority: int
    overridden: bool
    override_reason: str | None
    stored_score: Num
    scored_at: datetime
    stale: bool
    config_version: int
    criteria: list[CriterionOut]
    summary: str


class _PriorityConfigFields(BaseModel):
    weight_impact: int = Field(ge=0, le=1000)
    weight_urgency: int = Field(ge=0, le=1000)
    weight_affected_users: int = Field(ge=0, le=1000)
    weight_no_workaround: int = Field(ge=0, le=1000)
    weight_deadline: int = Field(ge=0, le=1000)
    p1_min: int = Field(ge=1, le=100)
    p2_min: int = Field(ge=1, le=100)
    p3_min: int = Field(ge=1, le=100)


class PriorityConfigIn(_PriorityConfigFields):
    # The version the client last saw (0 = defaults, nothing stored yet).
    version: int = Field(ge=0)


class PriorityConfigOut(_PriorityConfigFields):
    version: int
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class RecalculateOut(BaseModel):
    examined: int
    priority_changed: int
    overridden_skipped: int
