"""baseline

Revision ID: ca411dee21d0
Revises:
Create Date: 2026-06-19 14:11:26.423310

Creates the foundational schema from scratch (parent tables before the children
that reference them by FK) so a fresh database — CI and prod RDS — can build the
whole schema from migrations alone. Enum types are created up front with their
full value sets, which makes the later `ALTER TYPE ... ADD VALUE IF NOT EXISTS`
and the status-column enum cast (acdb3a268e6e) harmless no-ops. Money columns are
Numeric(12,2), never Float. Only baseline-era columns are created here; columns
added by later migrations (e.g. submissions.source, data_requests.category,
ledger.purchase_id, user_auth.mfa_*) are NOT created here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'ca411dee21d0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str):
    # Reference an already-created Postgres enum type without trying to (re)create it.
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    # Legacy scaffold from a much older create_all, if present.
    op.execute("DROP TABLE IF EXISTS user_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    # ------------------------------------------------------------------
    # Enum types — created with their FULL current value sets (idempotent).
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE user_role_enum AS ENUM ('REQUESTER', 'PROVIDER', 'ADMIN');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE pricing_mode_enum AS ENUM ('PER_UNIT', 'FIXED_BOUNTY');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE request_status_enum AS ENUM
                ('DRAFT', 'OPEN', 'PARTIALLY_FULFILLED', 'REVIEW', 'COMPLETED', 'EXPIRED');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE submission_status_enum AS ENUM
                ('PENDING', 'VALIDATED', 'REJECTED_INVALID', 'ACCEPTED',
                 'PARTIALLY_ACCEPTED', 'REJECTED', 'PAID', 'DISPUTED');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """)

    base_cols = lambda: [
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
    ]

    # ------------------------------------------------------------------
    # Parents first
    # ------------------------------------------------------------------
    op.create_table(
        'user_auth',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('refresh_token_hash', sa.String(), nullable=True),
        sa.Column('role', _enum('user_role_enum'), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('account_locked', sa.Boolean(), nullable=True),
        sa.Column('failed_login_attempts', sa.Integer(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('stripe_account_id', sa.String(), nullable=True),
        *base_cols(),
        sa.PrimaryKeyConstraint('id'),
    )
    # email = Column(unique=True, index=True) → a UNIQUE index; plus the named
    # __table_args__ index. (Matches the model so `alembic check` stays clean.)
    op.create_index('ix_user_auth_email', 'user_auth', ['email'], unique=True)
    op.create_index('idx_user_auth_email', 'user_auth', ['email'], unique=False)

    op.create_table(
        'licenses',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('terms', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        *base_cols(),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'user_profile',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('user_type', sa.String(), nullable=True),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('last_name', sa.String(), nullable=True),
        sa.Column('company_name', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('address', sa.String(), nullable=True),
        *base_cols(),
        sa.ForeignKeyConstraint(['user_id'], ['user_auth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('idx_user_profile_user_id', 'user_profile', ['user_id'], unique=False)

    op.create_table(
        'user_analytics',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('reputation_score', sa.Float(), nullable=True),
        sa.Column('total_transactions', sa.Integer(), nullable=True),
        sa.Column('successful_transactions', sa.Integer(), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(), nullable=True),
        sa.Column('provider_quality_score', sa.Float(), nullable=True),
        *base_cols(),
        sa.ForeignKeyConstraint(['user_id'], ['user_auth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('idx_user_analytics_user_id', 'user_analytics', ['user_id'], unique=False)

    op.create_table(
        'data_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('required_format', sa.String(), nullable=True),
        sa.Column('amount_required', sa.Integer(), nullable=True),
        sa.Column('budget', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('pricing_mode', _enum('pricing_mode_enum'), server_default='PER_UNIT', nullable=False),
        sa.Column('price_per_unit', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('unit', sa.String(), nullable=True),
        sa.Column('deadline', sa.DateTime(), nullable=True),
        sa.Column('spec', sa.JSON(), nullable=True),
        sa.Column('accepted_total', sa.Integer(), nullable=True),
        sa.Column('license_id', sa.UUID(), nullable=True),
        sa.Column('requester_id', sa.UUID(), nullable=True),
        sa.Column('status', _enum('request_status_enum'), nullable=False),
        *base_cols(),
        sa.ForeignKeyConstraint(['license_id'], ['licenses.id']),
        sa.ForeignKeyConstraint(['requester_id'], ['user_auth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_request_status_budget', 'data_requests', ['status', 'budget'], unique=False)
    op.create_index('idx_marketplace_matching', 'data_requests', ['status', 'budget', 'created_at'], unique=False)
    op.create_index('idx_request_active_records', 'data_requests', ['is_deleted', 'status'], unique=False)

    op.create_table(
        'submissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('request_id', sa.UUID(), nullable=True),
        sa.Column('provider_id', sa.UUID(), nullable=True),
        sa.Column('content_link', sa.String(), nullable=True),
        sa.Column('offered_amount', sa.Integer(), nullable=True),
        sa.Column('accepted_amount', sa.Integer(), nullable=True),
        sa.Column('validated_amount', sa.Integer(), nullable=True),
        sa.Column('amount_due', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('validation_report', sa.JSON(), nullable=True),
        sa.Column('status', _enum('submission_status_enum'), nullable=False),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=True),
        sa.Column('dataset_hash', sa.String(), nullable=True),
        sa.Column('access_token_id', sa.String(), nullable=True),
        sa.Column('download_limit', sa.Integer(), nullable=True),
        sa.Column('verified_by', sa.UUID(), nullable=True),
        sa.Column('review_notes', sa.Text(), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('storage_location', sa.String(), nullable=True),
        sa.Column('owner_signature', sa.String(), nullable=True),
        sa.Column('access_expiry', sa.DateTime(), nullable=True),
        *base_cols(),
        sa.ForeignKeyConstraint(['request_id'], ['data_requests.id']),
        sa.ForeignKeyConstraint(['provider_id'], ['user_auth.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_submission_request_status', 'submissions', ['request_id', 'status'], unique=False)
    op.create_index('idx_submission_active_records', 'submissions', ['is_deleted', 'status'], unique=False)

    # ------------------------------------------------------------------
    # Children that reference data_requests + submissions
    # ------------------------------------------------------------------
    op.create_table(
        'ledger',
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('submission_id', sa.UUID(), nullable=True),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('external_ref', sa.String(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        *base_cols(),
        sa.ForeignKeyConstraint(['request_id'], ['data_requests.id']),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_ledger_request_id', 'ledger', ['request_id'], unique=False)


def downgrade() -> None:
    # Children before parents.
    op.drop_index('idx_ledger_request_id', table_name='ledger')
    op.drop_table('ledger')
    op.drop_index('idx_submission_active_records', table_name='submissions')
    op.drop_index('idx_submission_request_status', table_name='submissions')
    op.drop_table('submissions')
    op.drop_index('idx_request_active_records', table_name='data_requests')
    op.drop_index('idx_marketplace_matching', table_name='data_requests')
    op.drop_index('idx_request_status_budget', table_name='data_requests')
    op.drop_table('data_requests')
    op.drop_index('idx_user_analytics_user_id', table_name='user_analytics')
    op.drop_table('user_analytics')
    op.drop_index('idx_user_profile_user_id', table_name='user_profile')
    op.drop_table('user_profile')
    op.drop_table('licenses')
    op.drop_index('idx_user_auth_email', table_name='user_auth')
    op.drop_table('user_auth')

    op.execute("DROP TYPE IF EXISTS submission_status_enum")
    op.execute("DROP TYPE IF EXISTS request_status_enum")
    op.execute("DROP TYPE IF EXISTS pricing_mode_enum")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
