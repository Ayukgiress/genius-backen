"""normalize interview session lifecycle states

Revision ID: f7a21d9c4b60
Revises: b4c29f7610e8
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7a21d9c4b60'
down_revision: Union[str, Sequence[str], None] = 'b4c29f7610e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE interviews SET status = 'waiting_for_user' WHERE status = 'ongoing'"
    )
    op.alter_column(
        'interviews',
        'status',
        existing_type=sa.String(length=20),
        server_default='started',
    )


def downgrade() -> None:
    op.execute(
        "UPDATE interviews SET status = 'ongoing' "
        "WHERE status IN ('started', 'active', 'listening', 'ai_speaking', 'waiting_for_user', 'no_speech', 'failed')"
    )
    op.alter_column(
        'interviews',
        'status',
        existing_type=sa.String(length=20),
        server_default=None,
    )
