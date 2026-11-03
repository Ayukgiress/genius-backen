"""add audio_data to interview_messages

Revision ID: 9d1541f21fc3
Revises: 9d7b9b6876fd
Create Date: 2026-05-07 18:02:29.318997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d1541f21fc3'
down_revision: Union[str, Sequence[str], None] = '9d7b9b6876fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('interview_messages', sa.Column('audio_data', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('interview_messages', 'audio_data')
