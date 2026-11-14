"""Add the teacher role and its database constraint."""
from alembic import op


revision = "v4_7_teacher_role"
down_revision = "v4_7_html_category_bundles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "role IN ('learning_user','teacher','researcher','production_engineer','review_expert','admin','system_admin')",
        "users",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role",
        "role IN ('learning_user','researcher','production_engineer','review_expert','admin','system_admin')",
        "users",
    )
