"""Require manual review for diagnostic knowledge cases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202610140001"
down_revision: str | None = "202607110007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "aiops_diagnostic_cases",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column("aiops_diagnostic_cases", sa.Column("confirmed_by", sa.String(80)))
    op.add_column("aiops_diagnostic_cases", sa.Column("confirmed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("aiops_diagnostic_cases") as batch:
        batch.drop_column("confirmed_at")
        batch.drop_column("confirmed_by")
        batch.drop_column("review_status")
