"""add offer/session approval and admin soft-delete workflow

Revision ID: 3d7a1c2b4e5f
Revises: c8d4e6f1a2b3
"""
from alembic import op
import sqlalchemy as sa

revision = "3d7a1c2b4e5f"
down_revision = "c8d4e6f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    offer_columns = {c["name"] for c in inspector.get_columns("offer")}
    with op.batch_alter_table("offer") as batch_op:
        if "approval_status" not in offer_columns:
            batch_op.add_column(sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="pending"))
        if "approval_note" not in offer_columns:
            batch_op.add_column(sa.Column("approval_note", sa.Text(), nullable=True))
        if "material_url" not in offer_columns:
            batch_op.add_column(sa.Column("material_url", sa.String(length=500), nullable=True))
        if "material_file" not in offer_columns:
            batch_op.add_column(sa.Column("material_file", sa.String(length=255), nullable=True))
        if "material_name" not in offer_columns:
            batch_op.add_column(sa.Column("material_name", sa.String(length=255), nullable=True))

    # Existing offers were already visible and have not gone through this new queue.
    op.execute("UPDATE offer SET approval_status = 'approved' WHERE approval_status = 'pending'")

    request_columns = {c["name"] for c in inspector.get_columns("request")}
    with op.batch_alter_table("request") as batch_op:
        if "deleted_at" not in request_columns:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if "deleted_by_id" not in request_columns:
            batch_op.add_column(sa.Column("deleted_by_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_request_deleted_by", "user", ["deleted_by_id"], ["id"])

    session_columns = {c["name"] for c in inspector.get_columns("session")}
    with op.batch_alter_table("session") as batch_op:
        if "recording_approval_status" not in session_columns:
            batch_op.add_column(sa.Column("recording_approval_status", sa.String(length=20), nullable=False, server_default="none"))
        if "recording_review_note" not in session_columns:
            batch_op.add_column(sa.Column("recording_review_note", sa.Text(), nullable=True))
        if "deleted_at" not in session_columns:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        if "deleted_by_id" not in session_columns:
            batch_op.add_column(sa.Column("deleted_by_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_session_deleted_by", "user", ["deleted_by_id"], ["id"])

    # Preserve existing completed/recorded sessions: uploaded recordings become approved.
    op.execute("UPDATE session SET recording_approval_status = 'approved' WHERE recording_url IS NOT NULL AND recording_approval_status = 'none'")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "session" in inspector.get_table_names():
        with op.batch_alter_table("session") as batch_op:
            for name in ["fk_session_deleted_by"]:
                try: batch_op.drop_constraint(name, type_="foreignkey")
                except Exception: pass
            for name in ["deleted_by_id", "deleted_at", "recording_review_note", "recording_approval_status"]:
                if name in {c["name"] for c in inspector.get_columns("session")}: batch_op.drop_column(name)
    if "request" in inspector.get_table_names():
        with op.batch_alter_table("request") as batch_op:
            try: batch_op.drop_constraint("fk_request_deleted_by", type_="foreignkey")
            except Exception: pass
            for name in ["deleted_by_id", "deleted_at"]:
                if name in {c["name"] for c in inspector.get_columns("request")}: batch_op.drop_column(name)
    if "offer" in inspector.get_table_names():
        with op.batch_alter_table("offer") as batch_op:
            for name in ["material_name", "material_file", "material_url", "approval_note", "approval_status"]:
                if name in {c["name"] for c in inspector.get_columns("offer")}: batch_op.drop_column(name)
