"""add nullable video-person interview metadata

Revision ID: c3e8b1a2f6d4
Revises: f7a21d9c4b60
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3e8b1a2f6d4"
down_revision: Union[str, Sequence[str], None] = "f7a21d9c4b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Startup may have already added nullable columns to a legacy database.
    # IF NOT EXISTS keeps a later Alembic upgrade safe and repeatable.
    op.execute("ALTER TABLE interview_messages ADD COLUMN IF NOT EXISTS avatar_id VARCHAR(100) NULL")
    op.execute("ALTER TABLE interview_messages ADD COLUMN IF NOT EXISTS video_url TEXT NULL")
    op.execute("ALTER TABLE interview_messages ADD COLUMN IF NOT EXISTS speaking_state VARCHAR(30) NULL")
    op.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS persona_config JSONB NULL")
    op.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS session_metadata JSONB NULL")
    op.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS interviewer_type VARCHAR(50) NULL")
    op.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS camera_settings JSONB NULL")
    op.execute("ALTER TABLE interviews ADD COLUMN IF NOT EXISTS audio_settings JSONB NULL")
    op.execute(
        "UPDATE interview_messages SET video_url = ai_avatar_video_url "
        "WHERE video_url IS NULL AND ai_avatar_video_url IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("interviews", "audio_settings")
    op.drop_column("interviews", "camera_settings")
    op.drop_column("interviews", "interviewer_type")
    op.drop_column("interviews", "session_metadata")
    op.drop_column("interviews", "persona_config")
    op.drop_column("interview_messages", "speaking_state")
    op.drop_column("interview_messages", "video_url")
    op.drop_column("interview_messages", "avatar_id")
