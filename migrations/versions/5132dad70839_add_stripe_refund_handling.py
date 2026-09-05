"""add stripe refund handling

Revision ID: 5132dad70839
Revises: b2daf1499aa9
Create Date: 2026-08-18 19:26:18.649778

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5132dad70839"
down_revision = "b2daf1499aa9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("purchase", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "stripe_checkout_session_id",
                sa.String(length=255),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "stripe_payment_intent_id",
                sa.String(length=255),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "refunded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false()
            )
        )

        batch_op.add_column(
            sa.Column(
                "refunded_at",
                sa.DateTime(),
                nullable=True
            )
        )

        batch_op.add_column(
            sa.Column(
                "stripe_refund_id",
                sa.String(length=255),
                nullable=True
            )
        )

        # IMPORTANT:
        # SQLite/Alembic requires names for constraints.
        batch_op.create_unique_constraint(
            "uq_purchase_stripe_payment_intent",
            ["stripe_payment_intent_id"]
        )

        batch_op.create_unique_constraint(
            "uq_purchase_stripe_checkout_session",
            ["stripe_checkout_session_id"]
        )

        batch_op.create_unique_constraint(
            "uq_purchase_stripe_refund",
            ["stripe_refund_id"]
        )


def downgrade():
    with op.batch_alter_table("purchase", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_purchase_stripe_refund",
            type_="unique"
        )

        batch_op.drop_constraint(
            "uq_purchase_stripe_checkout_session",
            type_="unique"
        )

        batch_op.drop_constraint(
            "uq_purchase_stripe_payment_intent",
            type_="unique"
        )

        batch_op.drop_column("stripe_refund_id")
        batch_op.drop_column("refunded_at")
        batch_op.drop_column("refunded")
        batch_op.drop_column("stripe_payment_intent_id")
        batch_op.drop_column("stripe_checkout_session_id")