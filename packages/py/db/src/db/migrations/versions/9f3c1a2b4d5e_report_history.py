"""report_history table (reporting builder history)

Revision ID: 9f3c1a2b4d5e
Revises:
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision = "9f3c1a2b4d5e"
down_revision = None
branch_labels = ("database/postgres",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=False, server_default=""),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("css", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("report_history")
