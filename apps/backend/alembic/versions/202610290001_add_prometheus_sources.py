"""add prometheus data source table for the metrics explorer

Revision ID: 202610290001
Revises: 202610170001
Create Date: 2026-10-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202610290001"
down_revision: str | None = "202610170001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prometheus_sources",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("username", sa.String(length=240), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_series", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_prometheus_sources_owner_name"),
    )
    op.create_index(
        "ix_prometheus_sources_owner_updated",
        "prometheus_sources",
        ["owner_user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_prometheus_sources_owner_updated", table_name="prometheus_sources")
    op.drop_table("prometheus_sources")
