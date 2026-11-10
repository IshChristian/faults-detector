"""Sessions remember the RQ job processing them, so a lost job can be detected.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN job_id VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN job_id")
