"""add report model and newer fields

Revision ID: 5793d6870da7
Revises: 2291e4f7b17d
"""

from alembic import op
import sqlalchemy as sa


revision = "5793d6870da7"
down_revision = "2291e4f7b17d"
branch_labels = None
depends_on = None


def upgrade():
    # report already exists on some deployed databases, so only
    # create it when it is actually missing.
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "report" not in inspector.get_table_names():
        op.create_table(
            "report",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("reporter_id", sa.Integer(), nullable=False),
            sa.Column("offer_id", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.Integer(), nullable=True),
            sa.Column("comment_id", sa.Integer(), nullable=True),
            sa.Column("session_id", sa.Integer(), nullable=True),
            sa.Column("target_key", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("resolved_by_id", sa.Integer(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolution_note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["comment_id"], ["comment.id"]),
            sa.ForeignKeyConstraint(["offer_id"], ["offer.id"]),
            sa.ForeignKeyConstraint(["reporter_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["request_id"], ["request.id"]),
            sa.ForeignKeyConstraint(["resolved_by_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "reporter_id",
                "target_key",
                name="unique_report_per_user_per_target",
            ),
        )

    columns = {column["name"] for column in inspector.get_columns("feedback")}
    if "hidden" not in columns:
        with op.batch_alter_table("feedback") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "hidden",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    columns = {column["name"] for column in inspector.get_columns("session")}
    if "recording_hidden" not in columns:
        with op.batch_alter_table("session") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "recording_hidden",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    columns = {column["name"] for column in inspector.get_columns("user")}
    if "is_admin" not in columns:
        with op.batch_alter_table("user") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_admin",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "user" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("user")}
        if "is_admin" in columns:
            with op.batch_alter_table("user") as batch_op:
                batch_op.drop_column("is_admin")

    if "session" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("session")}
        if "recording_hidden" in columns:
            with op.batch_alter_table("session") as batch_op:
                batch_op.drop_column("recording_hidden")

    if "feedback" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("feedback")}
        if "hidden" in columns:
            with op.batch_alter_table("feedback") as batch_op:
                batch_op.drop_column("hidden")

    if "report" in inspector.get_table_names():
        op.drop_table("report")