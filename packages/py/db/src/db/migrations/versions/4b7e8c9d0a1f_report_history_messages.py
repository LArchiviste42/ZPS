"""add messages JSON column to report_history

Revision ID: 4b7e8c9d0a1f
Revises: 9f3c1a2b4d5e
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from alembic import op

revision = "4b7e8c9d0a1f"
down_revision = "9f3c1a2b4d5e"
branch_labels = None  # continues the database/postgres branch started by 9f3c1a2b4d5e
depends_on = None


def upgrade() -> None:
    op.add_column("report_history", sa.Column("messages", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_history", "messages")
