"""add deterministic interview sessions and queryable analytics events

Revision ID: a6c42f9d1e30
Revises: c3e8b1a2f6d4
Create Date: 2026-11-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6c42f9d1e30"
down_revision: Union[str, Sequence[str], None] = "c3e8b1a2f6d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Preserve all historical sessions but mark duplicate open sessions as failed
    # before enforcing the one-open-session-per-user/job invariant.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY user_id, job_id
                       ORDER BY updated_at DESC, id DESC
                   ) AS session_rank
            FROM interviews
            WHERE status NOT IN ('completed', 'failed')
        )
        UPDATE interviews AS interview
        SET status = 'failed'
        FROM ranked
        WHERE interview.id = ranked.id
          AND ranked.session_rank > 1
        """
    )
    op.create_index(
        "ix_interviews_user_updated_at",
        "interviews",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_interviews_user_job_status",
        "interviews",
        ["user_id", "job_id", "status"],
    )
    op.create_index(
        "uq_interviews_user_job_open",
        "interviews",
        ["user_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed', 'failed')"),
    )

    op.add_column("analytics", sa.Column("interview_id", sa.Integer(), nullable=True))
    op.add_column("analytics", sa.Column("job_id", sa.String(length=50), nullable=True))
    op.create_foreign_key(
        "fk_analytics_interview_id_interviews",
        "analytics",
        "interviews",
        ["interview_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_analytics_interview_id", "analytics", ["interview_id"])
    op.create_index(
        "ix_analytics_user_event_created_at",
        "analytics",
        ["user_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_user_event_created_at", table_name="analytics")
    op.drop_index("ix_analytics_interview_id", table_name="analytics")
    op.drop_constraint("fk_analytics_interview_id_interviews", "analytics", type_="foreignkey")
    op.drop_column("analytics", "job_id")
    op.drop_column("analytics", "interview_id")
    op.drop_index("uq_interviews_user_job_open", table_name="interviews")
    op.drop_index("ix_interviews_user_job_status", table_name="interviews")
    op.drop_index("ix_interviews_user_updated_at", table_name="interviews")
