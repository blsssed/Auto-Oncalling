"""add active-alert snapshot table for recurring alert polling

Revision ID: 202610170001
Revises: 202610140001
Create Date: 2026-10-17 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202610170001"
down_revision: str | None = "202610140001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "active_alerts",
        sa.Column("id", sa.String(length=160), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=240), nullable=False),
        sa.Column("alert_name", sa.String(length=240), nullable=False),
        sa.Column("service", sa.String(length=240), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("starts_at", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_active_alerts_revision", "active_alerts", ["revision"])
    op.create_index("ix_active_alerts_recorded_at", "active_alerts", ["recorded_at"])
    op.create_table(
        "active_alert_snapshot_meta",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("active_alert_snapshot_meta")
    op.drop_table("active_alerts")