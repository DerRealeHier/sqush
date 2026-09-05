"""Fix GameUpdate model

Revision ID: f11de0a5e990
Revises: 801769bf969e
Create Date: 2026-08-11 20:06:38.610005
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f11de0a5e990"
down_revision = "801769bf969e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("game_update", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "view_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "link",
                sa.String(length=250),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_column("link")

    with op.batch_alter_table("game_update", schema=None) as batch_op:
        batch_op.drop_column("view_count")