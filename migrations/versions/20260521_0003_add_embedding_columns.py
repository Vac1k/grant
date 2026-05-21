"""add embedding columns for stage 7

Revision ID: 20260521_0003
Revises: 20260519_0002
Create Date: 2026-05-21 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = "20260521_0003"
down_revision: Union[str, None] = "20260519_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table_name in ("grants", "client_profiles", "application_history"):
        op.add_column(table_name, sa.Column("embedding", Vector(1536), nullable=True))
        op.add_column(table_name, sa.Column("embedding_text", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("embedding_model", sa.String(length=100), nullable=True))
        op.add_column(table_name, sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table_name in ("application_history", "client_profiles", "grants"):
        op.drop_column(table_name, "embedded_at")
        op.drop_column(table_name, "embedding_model")
        op.drop_column(table_name, "embedding_text")
        op.drop_column(table_name, "embedding")
