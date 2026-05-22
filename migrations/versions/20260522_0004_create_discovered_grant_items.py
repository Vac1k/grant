"""create discovered grant items for stage 1 link extraction

Revision ID: 20260522_0004
Revises: 20260521_0003
Create Date: 2026-05-22 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260522_0004"
down_revision: Union[str, None] = "20260521_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "discovered_grant_items",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_slug", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("title_hint", sa.Text(), nullable=True),
        sa.Column("summary_hint", sa.Text(), nullable=True),
        sa.Column("published_at_hint", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_hint", sa.Text(), nullable=True),
        sa.Column("listing_url", sa.Text(), nullable=True),
        sa.Column("listing_position", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("discovery_status", sa.String(length=50), nullable=False),
        sa.Column("detail_fetch_status", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_discovered_grant_items_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovered_grant_items")),
        sa.UniqueConstraint("source_id", "canonical_url", name="uq_discovered_items_canonical_url"),
        sa.UniqueConstraint("source_id", "source_record_id", name="uq_discovered_items_source_record_id"),
    )
    op.create_index(op.f("ix_discovered_grant_items_source_id"), "discovered_grant_items", ["source_id"], unique=False)
    op.create_index("ix_discovered_items_content_hash", "discovered_grant_items", ["source_id", "content_hash"], unique=False)
    op.create_index("ix_discovered_items_detail_status", "discovered_grant_items", ["source_id", "detail_fetch_status"], unique=False)
    op.create_index("ix_discovered_items_last_seen_at", "discovered_grant_items", ["last_seen_at"], unique=False)
    op.create_index("ix_discovered_items_source_status", "discovered_grant_items", ["source_id", "discovery_status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_discovered_items_source_status", table_name="discovered_grant_items")
    op.drop_index("ix_discovered_items_last_seen_at", table_name="discovered_grant_items")
    op.drop_index("ix_discovered_items_detail_status", table_name="discovered_grant_items")
    op.drop_index("ix_discovered_items_content_hash", table_name="discovered_grant_items")
    op.drop_index(op.f("ix_discovered_grant_items_source_id"), table_name="discovered_grant_items")
    op.drop_table("discovered_grant_items")
