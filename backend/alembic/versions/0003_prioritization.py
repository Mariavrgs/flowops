"""prioritization: scoring inputs, score snapshot, override, per-workspace configuration

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23

Existing issues (from Delivery 2) had a manually typed priority. Those are preserved by marking
them as manual overrides with an explicit reason, so the next recalculation does not silently
replace priorities a person chose.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("impact", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column("urgency", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column("affected_users", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column("has_workaround", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column("priority_score", sa.Numeric(5, 2), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "issues",
        sa.Column(
            "priority_scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("issues", sa.Column("priority_override_reason", sa.Text(), nullable=True))
    op.create_check_constraint("ck_issues_impact_range", "issues", "impact BETWEEN 1 AND 4")
    op.create_check_constraint("ck_issues_urgency_range", "issues", "urgency BETWEEN 1 AND 4")
    op.create_check_constraint(
        "ck_issues_affected_users_nonnegative", "issues", "affected_users >= 0"
    )
    op.create_check_constraint(
        "ck_issues_priority_score_range", "issues", "priority_score BETWEEN 0 AND 100"
    )
    op.create_check_constraint(
        "ck_issues_override_reason_not_blank",
        "issues",
        "priority_override_reason IS NULL OR length(btrim(priority_override_reason)) > 0",
    )
    op.execute(
        "UPDATE issues SET priority_override_reason = "
        "'Priority set manually before automatic prioritization existed (migration 0003)'"
    )

    op.add_column(
        "issue_changes",
        sa.Column("source", sa.String(length=20), server_default=sa.text("'user'"), nullable=False),
    )
    op.create_check_constraint(
        "ck_issue_changes_source_valid", "issue_changes", "source IN ('user', 'derived')"
    )

    op.create_table(
        "priority_configs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("weight_impact", sa.Integer(), nullable=False),
        sa.Column("weight_urgency", sa.Integer(), nullable=False),
        sa.Column("weight_affected_users", sa.Integer(), nullable=False),
        sa.Column("weight_no_workaround", sa.Integer(), nullable=False),
        sa.Column("weight_deadline", sa.Integer(), nullable=False),
        sa.Column("p1_min", sa.Integer(), nullable=False),
        sa.Column("p2_min", sa.Integer(), nullable=False),
        sa.Column("p3_min", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.CheckConstraint(
            "weight_impact >= 0 AND weight_urgency >= 0 AND weight_affected_users >= 0 "
            "AND weight_no_workaround >= 0 AND weight_deadline >= 0",
            name="ck_priority_configs_weights_nonnegative",
        ),
        sa.CheckConstraint(
            "weight_impact + weight_urgency + weight_affected_users + weight_no_workaround "
            "+ weight_deadline > 0",
            name="ck_priority_configs_weights_positive_sum",
        ),
        sa.CheckConstraint(
            "p1_min <= 100 AND p1_min > p2_min AND p2_min > p3_min AND p3_min >= 1",
            name="ck_priority_configs_thresholds_ordered",
        ),
        sa.CheckConstraint("version >= 1", name="ck_priority_configs_version_positive"),
    )


def downgrade() -> None:
    op.drop_table("priority_configs")
    op.drop_constraint("ck_issue_changes_source_valid", "issue_changes", type_="check")
    op.drop_column("issue_changes", "source")
    for name in (
        "ck_issues_override_reason_not_blank",
        "ck_issues_priority_score_range",
        "ck_issues_affected_users_nonnegative",
        "ck_issues_urgency_range",
        "ck_issues_impact_range",
    ):
        op.drop_constraint(name, "issues", type_="check")
    for column in (
        "priority_override_reason",
        "priority_scored_at",
        "priority_score",
        "has_workaround",
        "affected_users",
        "urgency",
        "impact",
    ):
        op.drop_column("issues", column)
