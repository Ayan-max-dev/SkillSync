"""Add mandatory password-change tracking.

Revision ID: d7e4f9a1b2c3
Revises: f2a7c9d1e4b6
"""
from alembic import op
import sqlalchemy as sa


revision = "d7e4f9a1b2c3"
down_revision = "f2a7c9d1e4b6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade():
    op.drop_column("user", "must_change_password")
