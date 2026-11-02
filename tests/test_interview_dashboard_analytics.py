import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_db",
)

from sqlalchemy.exc import IntegrityError

from app.crud.interview import get_or_create_interview
from app.models.analytics import Analytics
from app.schemas.interview import InterviewCreate
from app.services.analytics import track_interview_event


class DeterministicInterviewSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_open_session_for_same_user_and_job(self):
        existing = SimpleNamespace(id=7, job_id="job-1")
        with (
            patch(
                "app.crud.interview.get_open_interview_for_job",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch("app.crud.interview.create_interview", new_callable=AsyncMock) as create,
        ):
            interview, created = await get_or_create_interview(
                AsyncMock(), InterviewCreate(job_id="job-1"), user_id=42
            )

        self.assertIs(interview, existing)
        self.assertFalse(created)
        create.assert_not_awaited()

    async def test_concurrent_create_returns_winning_open_session(self):
        existing = SimpleNamespace(id=9, job_id="job-2")
        db = AsyncMock()
        integrity_error = IntegrityError("insert", {}, Exception("unique index"))
        with (
            patch(
                "app.crud.interview.get_open_interview_for_job",
                new_callable=AsyncMock,
                side_effect=[None, existing],
            ),
            patch(
                "app.crud.interview.create_interview",
                new_callable=AsyncMock,
                side_effect=integrity_error,
            ),
        ):
            interview, created = await get_or_create_interview(
                db, InterviewCreate(job_id="job-2"), user_id=42
            )

        self.assertIs(interview, existing)
        self.assertFalse(created)
        db.rollback.assert_awaited_once()


class InterviewAnalyticsEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_persists_structured_job_and_interview_references(self):
        with patch(
            "app.services.analytics.create_analytics_event",
            new_callable=AsyncMock,
        ) as create_event:
            await track_interview_event(
                AsyncMock(),
                user_id=42,
                event_type="interview_audio_processed",
                interview_id=7,
                job_id="job-1",
                payload={"status": "no_speech", "transcript_characters": 0},
            )

        event = create_event.await_args.args[1]
        self.assertEqual(event.user_id, 42)
        self.assertEqual(event.interview_id, 7)
        self.assertEqual(event.job_id, "job-1")
        self.assertEqual(event.event_type, "interview_audio_processed")
        self.assertEqual(event.payload["status"], "no_speech")

    def test_analytics_table_has_queryable_session_fields(self):
        columns = Analytics.__table__.columns
        self.assertTrue(columns["interview_id"].nullable)
        self.assertTrue(columns["job_id"].nullable)
        indexes = {index.name for index in Analytics.__table__.indexes}
        self.assertIn("ix_analytics_interview_id", indexes)
        self.assertIn("ix_analytics_user_event_created_at", indexes)


if __name__ == "__main__":
    unittest.main()
