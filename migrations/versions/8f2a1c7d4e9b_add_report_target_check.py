"""enforce exactly one report target

Revision ID: 8f2a1c7d4e9b
Revises: 5793d6870da7
"""
from alembic import op

revision = "8f2a1c7d4e9b"
down_revision = "5793d6870da7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("report", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "ck_report_exactly_one_target",
            "((offer_id IS NOT NULL) + (request_id IS NOT NULL) + (comment_id IS NOT NULL) + (session_id IS NOT NULL)) = 1",
        )


def downgrade():
    with op.batch_alter_table("report", schema=None) as batch_op:
        batch_op.drop_constraint("ck_report_exactly_one_target", type_="check")
