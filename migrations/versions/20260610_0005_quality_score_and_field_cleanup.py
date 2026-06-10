"""add persisted quality score fields and drop unused overengineered columns

Revision ID: 20260610_0005
Revises: 20260522_0004
Create Date: 2026-06-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260610_0005"
down_revision: Union[str, None] = "20260522_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 7: persisted quality score, tier, and flags for grants.
    op.add_column("grants", sa.Column("quality_score", sa.Integer(), nullable=True))
    op.add_column("grants", sa.Column("quality_tier", sa.String(length=50), nullable=True))
    op.add_column(
        "grants",
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.create_index("ix_grants_quality_tier", "grants", ["quality_tier"], unique=False)
    op.create_index("ix_grants_quality_score", "grants", ["quality_score"], unique=False)

    # Field review cleanup: columns that were written but never read by the app.
    op.drop_column("grants", "language")
    op.drop_column("grants", "opens_at")
    op.drop_column("grants", "extraction_method")
    op.drop_column("grants", "cofinancing_required")
    op.drop_column("grants", "consortium_required")
    op.drop_column("grants", "implementation_period_text")
    op.drop_column("grants", "contact_text")
    op.drop_column("sources", "requires_browser")
    op.drop_column("client_profiles", "source_type")
    op.drop_column("client_profiles", "source_uri")
    op.drop_column("match_runs", "run_type")

    # The reports table was never written by production code; the dashboard
    # report page renders live data instead.
    op.drop_index(op.f("ix_reports_match_run_id"), table_name="reports")
    op.drop_table("reports")


def downgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("match_run_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("format", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("report_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_run_id"],
            ["match_runs.id"],
            name=op.f("fk_reports_match_run_id_match_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_match_run_id"), "reports", ["match_run_id"], unique=False)

    op.add_column(
        "match_runs",
        sa.Column("run_type", sa.String(length=50), nullable=False, server_default=sa.text("'manual'")),
    )
    op.add_column("client_profiles", sa.Column("source_uri", sa.Text(), nullable=True))
    op.add_column(
        "client_profiles",
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default=sa.text("'manual'")),
    )
    op.add_column(
        "sources",
        sa.Column("requires_browser", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("grants", sa.Column("contact_text", sa.Text(), nullable=True))
    op.add_column("grants", sa.Column("implementation_period_text", sa.Text(), nullable=True))
    op.add_column("grants", sa.Column("consortium_required", sa.Boolean(), nullable=True))
    op.add_column("grants", sa.Column("cofinancing_required", sa.Boolean(), nullable=True))
    op.add_column("grants", sa.Column("extraction_method", sa.String(length=50), nullable=True))
    op.add_column("grants", sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("grants", sa.Column("language", sa.String(length=20), nullable=True))

    op.drop_index("ix_grants_quality_score", table_name="grants")
    op.drop_index("ix_grants_quality_tier", table_name="grants")
    op.drop_column("grants", "quality_flags")
    op.drop_column("grants", "quality_tier")
    op.drop_column("grants", "quality_score")
