"""Baseline: the original schema from the documentation pack (migrations/sql/0001_baseline.sql).

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).resolve().parents[1] / "sql" / "0001_baseline.sql"

# Reverse dependency order. alembic_version is left alone so Alembic can record the downgrade.
TABLES = [
    "audit_logs", "feedback_labels", "actions", "alert_deliveries", "events", "rules", "fault_types",
    "training_jobs", "model_assignments", "models", "zones", "cameras", "sites", "api_keys",
    "refresh_tokens", "users", "customers",
]


def _run_script(sql: str) -> None:
    # asyncpg runs a multi-statement script only through its own execute() without parameters;
    # SQLAlchemy's execute() would prepare it as a single statement.
    driver_conn = op.get_bind().connection.driver_connection
    await_only(driver_conn.execute(sql))


def upgrade() -> None:
    _run_script(SQL_FILE.read_text())


def downgrade() -> None:
    _run_script(
        "".join(f"DROP TABLE IF EXISTS {t} CASCADE;\n" for t in TABLES)
        + "DROP FUNCTION IF EXISTS audit_logs_block_changes();\n"
    )
