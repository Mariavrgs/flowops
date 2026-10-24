"""issues, status events, change log

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

STATUSES = "('open', 'in_progress', 'blocked', 'resolved', 'closed')"


def upgrade() -> None:
    op.create_table(
        "issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reopen_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "category_id"],
            ["categories.workspace_id", "categories.id"],
            name="fk_issues_category_same_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id", "workspace_id"],
            ["memberships.user_id", "memberships.workspace_id"],
            name="fk_issues_assignee_is_member",
        ),
        sa.UniqueConstraint("workspace_id", "id", name="uq_issues_workspace_id_id"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_issues_status_valid"),
        sa.CheckConstraint("priority BETWEEN 1 AND 4", name="ck_issues_priority_range"),
        sa.CheckConstraint(
            "due_at IS NULL OR due_at >= created_at", name="ck_issues_due_after_created"
        ),
        sa.CheckConstraint("version >= 1", name="ck_issues_version_positive"),
        sa.CheckConstraint("reopen_count >= 0", name="ck_issues_reopen_count_nonnegative"),
    )
    op.create_index(
        "ix_issues_workspace_status_priority_due",
        "issues",
        ["workspace_id", "status", "priority", "due_at"],
    )
    op.create_index("ix_issues_workspace_created_at", "issues", ["workspace_id", "created_at"])

    op.create_table(
        "issue_status_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "issue_id"],
            ["issues.workspace_id", "issues.id"],
            name="fk_status_events_issue_same_workspace",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"to_status IN {STATUSES}", name="ck_status_events_to_status_valid"),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN {STATUSES}",
            name="ck_status_events_from_status_valid",
        ),
    )
    op.create_index(
        "ix_status_events_issue_occurred", "issue_status_events", ["issue_id", "occurred_at"]
    )

    op.create_table(
        "issue_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=50), nullable=False),
        sa.Column("old_value", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("new_value", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "issue_id"],
            ["issues.workspace_id", "issues.id"],
            name="fk_issue_changes_issue_same_workspace",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_issue_changes_issue_version", "issue_changes", ["issue_id", "version"])


def downgrade() -> None:
    op.drop_index("ix_issue_changes_issue_version", table_name="issue_changes")
    op.drop_table("issue_changes")
    op.drop_index("ix_status_events_issue_occurred", table_name="issue_status_events")
    op.drop_table("issue_status_events")
    op.drop_index("ix_issues_workspace_created_at", table_name="issues")
    op.drop_index("ix_issues_workspace_status_priority_due", table_name="issues")
    op.drop_table("issues")
