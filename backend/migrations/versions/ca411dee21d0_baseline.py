"""baseline

Revision ID: ca411dee21d0
Revises:
Create Date: 2026-06-19 14:11:26.423310

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ca411dee21d0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # New tables
    # ------------------------------------------------------------------
    op.create_table(
        'licenses',
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('terms', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'ledger',
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('submission_id', sa.UUID(), nullable=True),
        sa.Column('entry_type', sa.String(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('external_ref', sa.String(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['request_id'], ['data_requests.id']),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_ledger_request_id', 'ledger', ['request_id'], unique=False)

    # ------------------------------------------------------------------
    # Drop legacy tables (old scaffold, replaced by user_auth / user_profile)
    # ------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS user_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    # ------------------------------------------------------------------
    # Enum additions — Postgres requires ALTER TYPE ... ADD VALUE
    # request_status_enum: add PARTIALLY_FULFILLED
    # submission_status_enum: add VALIDATED, REJECTED_INVALID,
    #                          PARTIALLY_ACCEPTED, PAID, DISPUTED
    # new enum: pricing_mode_enum
    # ------------------------------------------------------------------
    op.execute("ALTER TYPE request_status_enum ADD VALUE IF NOT EXISTS 'PARTIALLY_FULFILLED'")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'VALIDATED'")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'REJECTED_INVALID'")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'PARTIALLY_ACCEPTED'")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'PAID'")
    op.execute("ALTER TYPE submission_status_enum ADD VALUE IF NOT EXISTS 'DISPUTED'")

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE pricing_mode_enum AS ENUM ('PER_UNIT', 'FIXED_BOUNTY');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # data_requests — new columns
    # ------------------------------------------------------------------
    op.add_column('data_requests', sa.Column('pricing_mode',
        sa.Enum('PER_UNIT', 'FIXED_BOUNTY', name='pricing_mode_enum'),
        nullable=True))                        # nullable first, set default, then enforce below
    op.execute("UPDATE data_requests SET pricing_mode = 'PER_UNIT' WHERE pricing_mode IS NULL")
    op.alter_column('data_requests', 'pricing_mode', nullable=False)

    op.add_column('data_requests', sa.Column('price_per_unit', sa.Float(), nullable=True))
    op.add_column('data_requests', sa.Column('unit', sa.String(), nullable=True))
    op.add_column('data_requests', sa.Column('deadline', sa.DateTime(), nullable=True))
    op.add_column('data_requests', sa.Column('spec', sa.JSON(), nullable=True))
    op.add_column('data_requests', sa.Column('accepted_total', sa.Integer(), nullable=True))
    op.add_column('data_requests', sa.Column('license_id', sa.UUID(), nullable=True))
    op.add_column('data_requests', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('data_requests', sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.add_column('data_requests', sa.Column('is_deleted', sa.Boolean(), nullable=True))
    op.add_column('data_requests', sa.Column('version', sa.Integer(), nullable=True))

    op.execute("UPDATE data_requests SET is_deleted = FALSE WHERE is_deleted IS NULL")
    op.execute("UPDATE data_requests SET version = 1 WHERE version IS NULL")
    op.execute("UPDATE data_requests SET accepted_total = 0 WHERE accepted_total IS NULL")

    op.execute("DROP INDEX IF EXISTS ix_data_requests_id")
    op.create_index('idx_marketplace_matching', 'data_requests', ['status', 'budget', 'created_at'], unique=False)
    op.create_index('idx_request_active_records', 'data_requests', ['is_deleted', 'status'], unique=False)
    op.create_index('idx_request_status_budget', 'data_requests', ['status', 'budget'], unique=False)

    op.execute("ALTER TABLE data_requests DROP CONSTRAINT IF EXISTS data_requests_requester_id_fkey")
    op.create_foreign_key(None, 'data_requests', 'user_auth', ['requester_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key(None, 'data_requests', 'licenses', ['license_id'], ['id'])

    # ------------------------------------------------------------------
    # submissions — new columns
    # ------------------------------------------------------------------
    op.add_column('submissions', sa.Column('validated_amount', sa.Integer(), nullable=True))
    op.add_column('submissions', sa.Column('amount_due', sa.Float(), nullable=True))
    op.add_column('submissions', sa.Column('validation_report', sa.JSON(), nullable=True))
    op.add_column('submissions', sa.Column('dataset_hash', sa.String(), nullable=True))
    op.add_column('submissions', sa.Column('access_token_id', sa.String(), nullable=True))
    op.add_column('submissions', sa.Column('download_limit', sa.Integer(), nullable=True))
    op.add_column('submissions', sa.Column('verified_by', sa.UUID(), nullable=True))
    op.add_column('submissions', sa.Column('review_notes', sa.Text(), nullable=True))
    op.add_column('submissions', sa.Column('file_size_bytes', sa.Integer(), nullable=True))
    op.add_column('submissions', sa.Column('mime_type', sa.String(), nullable=True))
    op.add_column('submissions', sa.Column('storage_location', sa.String(), nullable=True))
    op.add_column('submissions', sa.Column('owner_signature', sa.String(), nullable=True))
    op.add_column('submissions', sa.Column('access_expiry', sa.DateTime(), nullable=True))
    op.add_column('submissions', sa.Column('is_deleted', sa.Boolean(), nullable=True))
    op.add_column('submissions', sa.Column('version', sa.Integer(), nullable=True))

    op.execute("UPDATE submissions SET is_deleted = FALSE WHERE is_deleted IS NULL")
    op.execute("UPDATE submissions SET version = 1 WHERE version IS NULL")

    op.execute("DROP INDEX IF EXISTS ix_submissions_id")
    op.create_index('idx_submission_active_records', 'submissions', ['is_deleted', 'status'], unique=False)
    op.create_index('idx_submission_request_status', 'submissions', ['request_id', 'status'], unique=False)

    op.execute("ALTER TABLE submissions DROP CONSTRAINT IF EXISTS submissions_provider_id_fkey")
    op.create_foreign_key(None, 'submissions', 'user_auth', ['provider_id'], ['id'], ondelete='CASCADE')

    # ------------------------------------------------------------------
    # user_auth — new columns
    # ------------------------------------------------------------------
    op.add_column('user_auth', sa.Column('stripe_account_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_auth', 'stripe_account_id')

    op.drop_index('idx_submission_request_status', table_name='submissions')
    op.drop_index('idx_submission_active_records', table_name='submissions')
    op.drop_column('submissions', 'version')
    op.drop_column('submissions', 'is_deleted')
    op.drop_column('submissions', 'access_expiry')
    op.drop_column('submissions', 'owner_signature')
    op.drop_column('submissions', 'storage_location')
    op.drop_column('submissions', 'mime_type')
    op.drop_column('submissions', 'file_size_bytes')
    op.drop_column('submissions', 'review_notes')
    op.drop_column('submissions', 'verified_by')
    op.drop_column('submissions', 'download_limit')
    op.drop_column('submissions', 'access_token_id')
    op.drop_column('submissions', 'dataset_hash')
    op.drop_column('submissions', 'validation_report')
    op.drop_column('submissions', 'amount_due')
    op.drop_column('submissions', 'validated_amount')

    op.drop_index('idx_request_status_budget', table_name='data_requests')
    op.drop_index('idx_request_active_records', table_name='data_requests')
    op.drop_index('idx_marketplace_matching', table_name='data_requests')
    op.drop_column('data_requests', 'version')
    op.drop_column('data_requests', 'is_deleted')
    op.drop_column('data_requests', 'updated_at')
    op.drop_column('data_requests', 'created_at')
    op.drop_column('data_requests', 'license_id')
    op.drop_column('data_requests', 'accepted_total')
    op.drop_column('data_requests', 'spec')
    op.drop_column('data_requests', 'deadline')
    op.drop_column('data_requests', 'unit')
    op.drop_column('data_requests', 'price_per_unit')
    op.drop_column('data_requests', 'pricing_mode')

    op.drop_index('idx_ledger_request_id', table_name='ledger')
    op.drop_table('ledger')
    op.drop_table('licenses')
