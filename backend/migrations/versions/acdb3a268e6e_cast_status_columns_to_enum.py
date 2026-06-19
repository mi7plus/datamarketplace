"""cast_status_columns_to_enum

Revision ID: acdb3a268e6e
Revises: ca411dee21d0
Create Date: 2026-06-19

Cast data_requests.status and submissions.status from VARCHAR to the proper
Postgres enum types created in the baseline migration.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'acdb3a268e6e'
down_revision: Union[str, Sequence[str], None] = 'ca411dee21d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE data_requests
        ALTER COLUMN status TYPE request_status_enum
        USING status::request_status_enum
    """)
    op.execute("ALTER TABLE data_requests ALTER COLUMN status SET NOT NULL")

    op.execute("""
        ALTER TABLE submissions
        ALTER COLUMN status TYPE submission_status_enum
        USING status::submission_status_enum
    """)
    op.execute("ALTER TABLE submissions ALTER COLUMN status SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE data_requests ALTER COLUMN status TYPE VARCHAR USING status::VARCHAR")
    op.execute("ALTER TABLE data_requests ALTER COLUMN status DROP NOT NULL")

    op.execute("ALTER TABLE submissions ALTER COLUMN status TYPE VARCHAR USING status::VARCHAR")
    op.execute("ALTER TABLE submissions ALTER COLUMN status DROP NOT NULL")
