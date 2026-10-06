"""message media reference

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("media", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "media")
