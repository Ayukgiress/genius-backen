"""add config and transcript_segments to interviews

Revision ID: b3c4d5e6f7a8_interview_config_and_transcript
Revises: a2b3c4d5e6f7_add_career_profiles_and_events
Create Date: 2026-11-03 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8_interview_config_and_transcript'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7_add_career_profiles_and_events'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'interviews',
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'interviews',
        sa.Column('transcript_segments', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('interviews', 'transcript_segments')
    op.drop_column('interviews', 'config')
