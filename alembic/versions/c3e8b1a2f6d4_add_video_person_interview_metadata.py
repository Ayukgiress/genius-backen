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
    op.add_column(
        "interview_messages",
        sa.Column("avatar_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "interview_messages",
        sa.Column("video_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "interview_messages",
        sa.Column("speaking_state", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("persona_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("session_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("interviewer_type", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("camera_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "interviews",
        sa.Column("audio_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
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
