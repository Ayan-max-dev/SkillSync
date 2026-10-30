"""add backward-compatible category to offers

Revision ID: f2a7c9d1e4b6
Revises: a91c5e7d2f40
"""
from alembic import op
import sqlalchemy as sa


revision = "f2a7c9d1e4b6"
down_revision = "a91c5e7d2f40"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("offer")}
    if "category" not in columns:
        with op.batch_alter_table("offer") as batch_op:
            batch_op.add_column(sa.Column("category", sa.String(length=80), nullable=True))
    op.execute(
        "UPDATE offer SET category = (SELECT category FROM skill WHERE skill.id = offer.skill_id) "
        "WHERE category IS NULL"
    )


def downgrade():
    bind = op.get_bind()
    if "category" in {column["name"] for column in sa.inspect(bind).get_columns("offer")}:
        with op.batch_alter_table("offer") as batch_op:
            batch_op.drop_column("category")
