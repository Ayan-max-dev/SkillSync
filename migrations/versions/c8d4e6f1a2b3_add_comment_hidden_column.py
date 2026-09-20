"""add comment hidden column

Revision ID: c8d4e6f1a2b3
Revises: 8f2a1c7d4e9b
"""
from alembic import op
import sqlalchemy as sa


revision = "c8d4e6f1a2b3"
down_revision = "8f2a1c7d4e9b"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("comment")}
    if "hidden" not in columns:
        with op.batch_alter_table("comment", schema=None) as batch_op:
            batch_op.add_column(sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("comment")}
    if "hidden" in columns:
        with op.batch_alter_table("comment", schema=None) as batch_op:
            batch_op.drop_column("hidden")