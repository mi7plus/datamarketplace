"""admin RBAC: admin_role + suspended on user_auth

Adds the orthogonal admin-privilege model (admin panel design, Option A fixed
sub-roles). Bootstraps any existing UserRole.ADMIN user to SUPER_ADMIN so current
admins keep full access. Postgres enums store the uppercase Python enum NAMES.

Revision ID: d8a1c2b3e4f5
Revises: d7e8f9a0b1c2
"""
from alembic import op
import sqlalchemy as sa

revision = "d8a1c2b3e4f5"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None

ADMIN_ROLE_LABELS = ("SUPER_ADMIN", "SUPPORT_LEAD", "SUPPORT_AGENT", "READ_ONLY")


def upgrade():
    bind = op.get_bind()
    # Create the enum type (idempotent guard for re-runs on a partially migrated DB).
    admin_role_enum = sa.Enum(*ADMIN_ROLE_LABELS, name="admin_role_enum")
    admin_role_enum.create(bind, checkfirst=True)

    op.add_column("user_auth", sa.Column("admin_role", admin_role_enum, nullable=True))
    op.add_column(
        "user_auth",
        sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Bootstrap: existing flat admins become super-admins (role stored as the NAME).
    op.execute("UPDATE user_auth SET admin_role = 'SUPER_ADMIN' WHERE role = 'ADMIN'")


def downgrade():
    op.drop_column("user_auth", "suspended")
    op.drop_column("user_auth", "admin_role")
    sa.Enum(name="admin_role_enum").drop(op.get_bind(), checkfirst=True)
