"""create stage 2 tables

Revision ID: 20260518_0001
Revises:
Create Date: 2026-05-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260518_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("list_url", sa.Text(), nullable=True),
        sa.Column("api_url", sa.Text(), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("sitemap_url", sa.Text(), nullable=True),
        sa.Column("access_strategy", sa.String(length=50), nullable=False),
        sa.Column("requires_browser", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rate_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint("slug", name=op.f("uq_sources_slug")),
    )
    op.create_table(
        "client_profiles",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("sector", sa.String(length=255), nullable=True),
        sa.Column("organization_type", sa.String(length=100), nullable=True),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("product_description", sa.Text(), nullable=True),
        sa.Column("risks", sa.Text(), nullable=True),
        sa.Column("target_topics", sa.JSON(), nullable=False),
        sa.Column("excluded_topics", sa.JSON(), nullable=False),
        sa.Column("previous_submissions_summary", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("profile_metadata", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_profiles")),
        sa.UniqueConstraint("slug", name=op.f("uq_client_profiles_slug")),
    )
    op.create_table(
        "match_runs",
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("run_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match_runs")),
    )
    op.create_index("ix_match_runs_status", "match_runs", ["status"], unique=False)
    op.create_table(
        "raw_grant_snapshots",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("raw_title", sa.Text(), nullable=True),
        sa.Column("raw_summary", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_raw_grant_snapshots_source_id_sources"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_grant_snapshots")),
        sa.UniqueConstraint("source_id", "source_url", "content_hash", name="uq_raw_grant_snapshots_source_url_hash"),
    )
    op.create_index(op.f("ix_raw_grant_snapshots_source_id"), "raw_grant_snapshots", ["source_id"], unique=False)
    op.create_index("ix_raw_grant_snapshots_source_record_id", "raw_grant_snapshots", ["source_id", "source_record_id"], unique=False)
    op.create_table(
        "grants",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("latest_raw_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("application_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_text", sa.Text(), nullable=True),
        sa.Column("program_name", sa.Text(), nullable=True),
        sa.Column("funder_name", sa.Text(), nullable=True),
        sa.Column("opportunity_type", sa.String(length=100), nullable=True),
        sa.Column("support_type", sa.String(length=100), nullable=True),
        sa.Column("funding_amount_min", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("funding_amount_max", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("funding_amount_text", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("geography_text", sa.Text(), nullable=True),
        sa.Column("countries", sa.JSON(), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("eligibility_text", sa.Text(), nullable=True),
        sa.Column("applicant_types", sa.JSON(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("restrictions_text", sa.Text(), nullable=True),
        sa.Column("cofinancing_required", sa.Boolean(), nullable=True),
        sa.Column("cofinancing_text", sa.Text(), nullable=True),
        sa.Column("consortium_required", sa.Boolean(), nullable=True),
        sa.Column("consortium_text", sa.Text(), nullable=True),
        sa.Column("implementation_period_text", sa.Text(), nullable=True),
        sa.Column("contact_text", sa.Text(), nullable=True),
        sa.Column("documents", sa.JSON(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("extraction_method", sa.String(length=50), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("extraction_metadata", sa.JSON(), nullable=False),
        sa.Column("needs_manual_review", sa.Boolean(), nullable=False),
        sa.Column("manual_review_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["latest_raw_snapshot_id"], ["raw_grant_snapshots.id"], name=op.f("fk_grants_latest_raw_snapshot_id_raw_grant_snapshots"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name=op.f("fk_grants_source_id_sources"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grants")),
        sa.UniqueConstraint("source_id", "source_record_id", name="uq_grants_source_record_id"),
        sa.UniqueConstraint("source_id", "source_url", name="uq_grants_source_url"),
    )
    op.create_index("ix_grants_deadline_at", "grants", ["deadline_at"], unique=False)
    op.create_index(op.f("ix_grants_source_id"), "grants", ["source_id"], unique=False)
    op.create_index("ix_grants_status", "grants", ["status"], unique=False)
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
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], name=op.f("fk_reports_match_run_id_match_runs"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_match_run_id"), "reports", ["match_run_id"], unique=False)
    op.create_table(
        "application_history",
        sa.Column("client_profile_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("grant_title", sa.Text(), nullable=False),
        sa.Column("grant_source", sa.String(length=255), nullable=True),
        sa.Column("program_name", sa.Text(), nullable=True),
        sa.Column("application_date", sa.Date(), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("applicant_type", sa.String(length=100), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("project_summary", sa.Text(), nullable=True),
        sa.Column("reusable_materials", sa.Text(), nullable=True),
        sa.Column("similarity_weight", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("history_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_profile_id"], ["client_profiles.id"], name=op.f("fk_application_history_client_profile_id_client_profiles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grant_id"], ["grants.id"], name=op.f("fk_application_history_grant_id_grants"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_history")),
    )
    op.create_index("ix_application_history_client_result", "application_history", ["client_profile_id", "result"], unique=False)
    op.create_index(op.f("ix_application_history_client_profile_id"), "application_history", ["client_profile_id"], unique=False)
    op.create_index("ix_application_history_program_name", "application_history", ["program_name"], unique=False)
    op.create_table(
        "grant_client_matches",
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("client_profile_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("hard_filter_passed", sa.Boolean(), nullable=False),
        sa.Column("filter_reasons", sa.JSON(), nullable=False),
        sa.Column("keyword_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("vector_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("history_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("llm_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("risks_text", sa.Text(), nullable=True),
        sa.Column("manual_checks", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("match_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_profile_id"], ["client_profiles.id"], name=op.f("fk_grant_client_matches_client_profile_id_client_profiles"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grant_id"], ["grants.id"], name=op.f("fk_grant_client_matches_grant_id_grants"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], name=op.f("fk_grant_client_matches_match_run_id_match_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grant_client_matches")),
        sa.UniqueConstraint("match_run_id", "grant_id", "client_profile_id", name="uq_grant_client_matches_run_grant_client"),
    )
    op.create_index(op.f("ix_grant_client_matches_client_profile_id"), "grant_client_matches", ["client_profile_id"], unique=False)
    op.create_index(op.f("ix_grant_client_matches_grant_id"), "grant_client_matches", ["grant_id"], unique=False)
    op.create_index(op.f("ix_grant_client_matches_match_run_id"), "grant_client_matches", ["match_run_id"], unique=False)
    op.create_index("ix_grant_client_matches_score", "grant_client_matches", ["score"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_grant_client_matches_score", table_name="grant_client_matches")
    op.drop_index(op.f("ix_grant_client_matches_match_run_id"), table_name="grant_client_matches")
    op.drop_index(op.f("ix_grant_client_matches_grant_id"), table_name="grant_client_matches")
    op.drop_index(op.f("ix_grant_client_matches_client_profile_id"), table_name="grant_client_matches")
    op.drop_table("grant_client_matches")
    op.drop_index("ix_application_history_program_name", table_name="application_history")
    op.drop_index(op.f("ix_application_history_client_profile_id"), table_name="application_history")
    op.drop_index("ix_application_history_client_result", table_name="application_history")
    op.drop_table("application_history")
    op.drop_index(op.f("ix_reports_match_run_id"), table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_grants_status", table_name="grants")
    op.drop_index(op.f("ix_grants_source_id"), table_name="grants")
    op.drop_index("ix_grants_deadline_at", table_name="grants")
    op.drop_table("grants")
    op.drop_index("ix_raw_grant_snapshots_source_record_id", table_name="raw_grant_snapshots")
    op.drop_index(op.f("ix_raw_grant_snapshots_source_id"), table_name="raw_grant_snapshots")
    op.drop_table("raw_grant_snapshots")
    op.drop_index("ix_match_runs_status", table_name="match_runs")
    op.drop_table("match_runs")
    op.drop_table("client_profiles")
    op.drop_table("sources")
