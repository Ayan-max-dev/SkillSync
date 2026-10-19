"""add session contribution certificates

Revision ID: a91c5e7d2f40
Revises: 3d7a1c2b4e5f
"""
from alembic import op
import sqlalchemy as sa

revision = "a91c5e7d2f40"
down_revision = "3d7a1c2b4e5f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "certificate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_code", sa.String(length=40), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("session.id"), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("issued_by_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("certificate_code", name="uq_certificate_code"),
        sa.UniqueConstraint("session_id", name="uq_certificate_session"),
    )
    op.create_index("ix_certificate_certificate_code", "certificate", ["certificate_code"], unique=True)


def downgrade():
    op.drop_index("ix_certificate_certificate_code", table_name="certificate")
    op.drop_table("certificate")
