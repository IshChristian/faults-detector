"""Cameras gain a mode: live (a Frigate camera) or upload (a recording position).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cameras ADD COLUMN mode VARCHAR(10) NOT NULL DEFAULT 'live' "
        "CONSTRAINT cameras_mode_check CHECK (mode IN ('live','upload'))"
    )
    op.execute(
        "ALTER TABLE cameras ADD CONSTRAINT cameras_live_needs_frigate_name "
        "CHECK (mode <> 'live' OR frigate_name IS NOT NULL) NOT VALID"
    )
    op.execute("ALTER TABLE cameras VALIDATE CONSTRAINT cameras_live_needs_frigate_name")


def downgrade() -> None:
    op.execute("ALTER TABLE cameras DROP CONSTRAINT cameras_live_needs_frigate_name")
    op.execute("ALTER TABLE cameras DROP COLUMN mode")
