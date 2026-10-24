from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        # Emails are normalized to lowercase by the application; the database enforces it,
        # so case-insensitive uniqueness cannot be bypassed by a code path that forgets to.
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("slug", name="uq_workspaces_slug"),)


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'agent', 'viewer')", name="ck_memberships_role_valid"),
        Index("ix_memberships_workspace_id", "workspace_id"),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("kind IN ('bug', 'incident', 'request')", name="ck_categories_kind_valid"),
        UniqueConstraint("workspace_id", "name", name="uq_categories_workspace_name"),
        # Redundant as a key (id is already unique) but required as the target of the composite
        # foreign key (workspace_id, category_id) that issues will use in Delivery 2. That FK
        # makes it impossible for an issue to reference a category of another workspace.
        UniqueConstraint("workspace_id", "id", name="uq_categories_workspace_id_id"),
    )


class AuthSession(Base):
    __tablename__ = "sessions"

    # SHA-256 hex of the random token stored in the cookie. A database leak does not expose
    # usable session tokens.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    category_id: Mapped[uuid.UUID] = mapped_column()
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    # Effective priority, 1 = most urgent ... 4 = least. Derived from priority_score unless
    # priority_override_reason is set (manual override).
    priority: Mapped[int] = mapped_column(SmallInteger)
    # Scoring inputs (see docs/PRIORITIZATION.md)
    impact: Mapped[int] = mapped_column(SmallInteger, server_default=text("2"))
    urgency: Mapped[int] = mapped_column(SmallInteger, server_default=text("2"))
    affected_users: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    has_workaround: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Snapshot of the score at the last rescoring. The live value can differ (deadline
    # proximity changes with time, and the workspace configuration can change).
    priority_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    priority_scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Non-NULL means a person overrode the computed priority, and this is why.
    priority_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Optimistic-lock counter: bumped by every successful change.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    reopen_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'blocked', 'resolved', 'closed')",
            name="ck_issues_status_valid",
        ),
        CheckConstraint("priority BETWEEN 1 AND 4", name="ck_issues_priority_range"),
        CheckConstraint("impact BETWEEN 1 AND 4", name="ck_issues_impact_range"),
        CheckConstraint("urgency BETWEEN 1 AND 4", name="ck_issues_urgency_range"),
        CheckConstraint("affected_users >= 0", name="ck_issues_affected_users_nonnegative"),
        CheckConstraint("priority_score BETWEEN 0 AND 100", name="ck_issues_priority_score_range"),
        CheckConstraint(
            "priority_override_reason IS NULL OR length(btrim(priority_override_reason)) > 0",
            name="ck_issues_override_reason_not_blank",
        ),
        CheckConstraint(
            "due_at IS NULL OR due_at >= created_at", name="ck_issues_due_after_created"
        ),
        CheckConstraint("version >= 1", name="ck_issues_version_positive"),
        CheckConstraint("reopen_count >= 0", name="ck_issues_reopen_count_nonnegative"),
        UniqueConstraint("workspace_id", "id", name="uq_issues_workspace_id_id"),
        # The three composite FKs below make cross-workspace references impossible at the
        # database level, even if application code has a bug.
        ForeignKeyConstraint(
            ["workspace_id", "category_id"],
            ["categories.workspace_id", "categories.id"],
            name="fk_issues_category_same_workspace",
        ),
        # Assignee must be a member of the issue's workspace. When assignee_id is NULL the
        # FK is not checked (MATCH SIMPLE), which is what we want for "unassigned".
        ForeignKeyConstraint(
            ["assignee_id", "workspace_id"],
            ["memberships.user_id", "memberships.workspace_id"],
            name="fk_issues_assignee_is_member",
        ),
        Index(
            "ix_issues_workspace_status_priority_due",
            "workspace_id",
            "status",
            "priority",
            "due_at",
        ),
        Index("ix_issues_workspace_created_at", "workspace_id", "created_at"),
    )


class IssueStatusEvent(Base):
    """Append-only timeline of status changes. The single source of truth for SLA and metrics."""

    __tablename__ = "issue_status_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column()
    issue_id: Mapped[uuid.UUID] = mapped_column()
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "issue_id"],
            ["issues.workspace_id", "issues.id"],
            name="fk_status_events_issue_same_workspace",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "to_status IN ('open', 'in_progress', 'blocked', 'resolved', 'closed')",
            name="ck_status_events_to_status_valid",
        ),
        CheckConstraint(
            "from_status IS NULL OR "
            "from_status IN ('open', 'in_progress', 'blocked', 'resolved', 'closed')",
            name="ck_status_events_from_status_valid",
        ),
        Index("ix_status_events_issue_occurred", "issue_id", "occurred_at"),
    )


class IssueChange(Base):
    """Human-facing audit log: one row per changed field, including status."""

    __tablename__ = "issue_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column()
    issue_id: Mapped[uuid.UUID] = mapped_column()
    field: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The issue version AFTER this change. Lets a 409 report which fields others changed.
    version: Mapped[int] = mapped_column(Integer)
    # "user": the actor edited this field. "derived": a consequence of rescoring (the actor
    # edited an input, or ran a recalculation, and the computed priority moved).
    source: Mapped[str] = mapped_column(String(20), server_default=text("'user'"))

    __table_args__ = (
        CheckConstraint("source IN ('user', 'derived')", name="ck_issue_changes_source_valid"),
        ForeignKeyConstraint(
            ["workspace_id", "issue_id"],
            ["issues.workspace_id", "issues.id"],
            name="fk_issue_changes_issue_same_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_issue_changes_issue_version", "issue_id", "version"),
    )


class PriorityConfigRow(Base):
    """One row per workspace. A workspace without a row uses the defaults (version 0)."""

    __tablename__ = "priority_configs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    weight_impact: Mapped[int] = mapped_column(Integer)
    weight_urgency: Mapped[int] = mapped_column(Integer)
    weight_affected_users: Mapped[int] = mapped_column(Integer)
    weight_no_workaround: Mapped[int] = mapped_column(Integer)
    weight_deadline: Mapped[int] = mapped_column(Integer)
    p1_min: Mapped[int] = mapped_column(Integer)
    p2_min: Mapped[int] = mapped_column(Integer)
    p3_min: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint(
            "weight_impact >= 0 AND weight_urgency >= 0 AND weight_affected_users >= 0 "
            "AND weight_no_workaround >= 0 AND weight_deadline >= 0",
            name="ck_priority_configs_weights_nonnegative",
        ),
        CheckConstraint(
            "weight_impact + weight_urgency + weight_affected_users + weight_no_workaround "
            "+ weight_deadline > 0",
            name="ck_priority_configs_weights_positive_sum",
        ),
        CheckConstraint(
            "p1_min <= 100 AND p1_min > p2_min AND p2_min > p3_min AND p3_min >= 1",
            name="ck_priority_configs_thresholds_ordered",
        ),
        CheckConstraint("version >= 1", name="ck_priority_configs_version_positive"),
    )
