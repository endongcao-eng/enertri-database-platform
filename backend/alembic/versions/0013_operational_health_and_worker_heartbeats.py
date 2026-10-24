"""Add worker liveness records used by health/readiness checks."""
from alembic import op
import sqlalchemy as sa


revision = "v4_7_operational_health"
down_revision = "v4_7_space_energy_literature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=160), primary_key=True),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("version", sa.String(length=80), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_worker_heartbeats_status", "worker_heartbeats", ["status"])
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_last_seen_at", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_status", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
