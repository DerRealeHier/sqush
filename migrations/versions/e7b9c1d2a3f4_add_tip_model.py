"""add tip model

Revision ID: e7b9c1d2a3f4
Revises: 9a0cbbb7114a
Create Date: 2026-09-03 15:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7b9c1d2a3f4'
down_revision = '9a0cbbb7114a'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = inspector.get_table_names()
    if 'tip' not in tables:
        op.create_table(
            'tip',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=True),
            sa.Column('developer_id', sa.Integer(), nullable=False),
            sa.Column('game_id', sa.Integer(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('message', sa.String(length=500), nullable=True),
            sa.Column('supporter_name', sa.String(length=64), nullable=True),
            sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=True),
            sa.Column('stripe_payment_intent_id', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['developer_id'], ['user.id'], ),
            sa.ForeignKeyConstraint(['game_id'], ['game.id'], ),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('stripe_checkout_session_id')
        )
        with op.batch_alter_table('tip', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_tip_developer_id'), ['developer_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_tip_game_id'), ['game_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_tip_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('tip', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tip_user_id'))
        batch_op.drop_index(batch_op.f('ix_tip_game_id'))
        batch_op.drop_index(batch_op.f('ix_tip_developer_id'))
    op.drop_table('tip')
