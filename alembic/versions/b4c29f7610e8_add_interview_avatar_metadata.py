"""add optional avatar and playback metadata to interview messages

Revision ID: b4c29f7610e8
Revises: 9d1541f21fc3
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4c29f7610e8'
down_revision: Union[str, Sequence[str], None] = '9d1541f21fc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interview_messages', sa.Column('ai_avatar_video_url', sa.Text(), nullable=True))
    op.add_column('interview_messages', sa.Column('avatar_type', sa.String(length=80), nullable=True))
    op.add_column('interview_messages', sa.Column('avatar_style', sa.String(length=100), nullable=True))
    op.add_column('interview_messages', sa.Column('response_mode', sa.String(length=50), nullable=True))
    op.add_column('interview_messages', sa.Column('persona', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('interview_messages', sa.Column('video_status', sa.String(length=50), nullable=True))
    op.add_column('interview_messages', sa.Column('playback_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('interview_messages', 'playback_metadata')
    op.drop_column('interview_messages', 'video_status')
    op.drop_column('interview_messages', 'persona')
    op.drop_column('interview_messages', 'response_mode')
    op.drop_column('interview_messages', 'avatar_style')
    op.drop_column('interview_messages', 'avatar_type')
    op.drop_column('interview_messages', 'ai_avatar_video_url')
