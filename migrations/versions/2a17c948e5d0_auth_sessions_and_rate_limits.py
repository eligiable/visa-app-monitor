"""Add CSRF session tokens and persistent authentication rate limits.

Revision ID: 2a17c948e5d0
Revises: 90b3f2469e7f
Create Date: 2026-11-09 01:04:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2a17c948e5d0"
down_revision: Union[str, None] = "90b3f2469e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist CSRF token hashes and database-backed login rate buckets."""
    op.add_column(
        "administrator_sessions",
        sa.Column("csrf_token_hash", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE administrator_sessions "
            "SET csrf_token_hash = token_hash, revoked_at = CURRENT_TIMESTAMP "
            "WHERE csrf_token_hash IS NULL"
        )
    )
    with op.batch_alter_table("administrator_sessions") as batch_op:
        batch_op.alter_column("csrf_token_hash", nullable=False)

    op.create_table(
        "auth_rate_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f("ck_auth_rate_limits_nonnegative_failure_count"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_rate_limits")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_auth_rate_limits_key_hash")),
    )
    op.create_index(
        "ix_auth_rate_limits_updated_at",
        "auth_rate_limits",
        ["updated_at"],
    )


def downgrade() -> None:
    """Remove login rate buckets and the CSRF token hash."""
    op.drop_index("ix_auth_rate_limits_updated_at", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")
    with op.batch_alter_table("administrator_sessions") as batch_op:
        batch_op.drop_column("csrf_token_hash")
