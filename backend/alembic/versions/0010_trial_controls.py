"""Persistent authentication and budget controls."""
from alembic import op
import sqlalchemy as sa
revision="v4_7_trial_controls"
down_revision="v4_7_web_trial"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("users",sa.Column("token_version",sa.Integer(),nullable=False,server_default="0"))
    op.add_column("users",sa.Column("must_change_password",sa.Boolean(),nullable=False,server_default=sa.false()))
    op.execute("UPDATE users SET token_version=1, must_change_password=true")
    op.create_table("safety_locks",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("value",sa.Integer(),nullable=False))
    op.execute("INSERT INTO safety_locks (id,value) VALUES (1,0)")
    op.create_table("rate_buckets",sa.Column("key",sa.String(64),primary_key=True),sa.Column("count",sa.Integer(),nullable=False),sa.Column("expires_at",sa.Integer(),nullable=False))
    op.create_index("ix_rate_buckets_expires_at","rate_buckets",["expires_at"])
    op.create_table("ai_budget_reservations",sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id"),nullable=False),sa.Column("day",sa.String(10),nullable=False),sa.Column("reserved_usd_micros",sa.Integer(),nullable=False),sa.Column("expires_at",sa.Integer(),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("usage_json",sa.Text()))
    op.create_index("ix_ai_budget_day","ai_budget_reservations",["day","user_id"])

def downgrade():
    op.drop_table("ai_budget_reservations")
    op.drop_table("rate_buckets")
    op.drop_table("safety_locks")
    op.drop_column("users","must_change_password")
    op.drop_column("users","token_version")
