"""Add encrypted notification integration settings.

Revision ID: 3c5a1f7e9b20
Revises: 2a17c948e5d0
Create Date: 2026-11-09 13:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3c5a1f7e9b20"
down_revision: Union[str, None] = "2a17c948e5d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store notification settings as an authenticated-encrypted payload."""
    op.create_table(
        "notification_integrations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("encrypted_configuration", sa.Text(), nullable=False),
        sa.Column("updated_by_administrator_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('TELEGRAM', 'EMAIL')",
            name=op.f("ck_notification_integrations_channel"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_administrator_id"],
            ["administrators.id"],
            name=op.f(
                "fk_notification_integrations_updated_by_administrator_id_"
                "administrators"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_integrations")),
        sa.UniqueConstraint("channel", name=op.f("uq_notification_integrations_channel")),
    )


def downgrade() -> None:
    """Remove encrypted notification integration settings."""
    op.drop_table("notification_integrations")