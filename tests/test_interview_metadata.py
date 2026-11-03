import os
import unittest
from unittest.mock import AsyncMock, MagicMock

# SQLAlchemy models register against the application's declarative Base. A
# placeholder URL is sufficient for metadata tests; no database connection is made.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_db",
)

from app.models.interview import Interview, InterviewMessage
from app.crud.interview import create_interview, create_interview_message
from app.schemas.interview import (
    InterviewCreate,
    InterviewMessageCreate,
    InterviewMessageResponse,
)


class InterviewMetadataCompatibilityTests(unittest.TestCase):
    def test_new_model_fields_are_nullable(self):
        message_columns = InterviewMessage.__table__.columns
        interview_columns = Interview.__table__.columns

        for name in (
            "avatar_style",
            "avatar_id",
            "video_url",
            "video_status",
            "response_mode",
            "speaking_state",
        ):
            with self.subTest(field=name):
                self.assertTrue(message_columns[name].nullable)

        for name in (
            "persona_config",
            "session_metadata",
            "interviewer_type",
            "camera_settings",
            "audio_settings",
        ):
            with self.subTest(field=name):
                self.assertTrue(interview_columns[name].nullable)

    def test_legacy_message_deserializes_with_new_fields_unset(self):
        legacy_message = InterviewMessageResponse(
            id=1,
            interview_id=2,
            role="assistant",
            content="Welcome to the interview.",
        )
        self.assertIsNone(legacy_message.avatar_style)
        self.assertIsNone(legacy_message.avatar_id)
        self.assertIsNone(legacy_message.video_url)
        self.assertIsNone(legacy_message.video_status)
        self.assertIsNone(legacy_message.response_mode)
        self.assertIsNone(legacy_message.speaking_state)

    def test_interview_settings_are_optional_and_serializable(self):
        legacy_request = InterviewCreate(job_id="job-1")
        self.assertIsNone(legacy_request.persona_config)
        self.assertIsNone(legacy_request.camera_settings)

        configured_request = InterviewCreate(
            job_id="job-2",
            persona_config={"name": "Avery", "voice": "neutral"},
            session_metadata={"client": "web"},
            interviewer_type="video_person",
            camera_settings={"enabled": True, "facing_mode": "user"},
            audio_settings={"enabled": True, "sample_rate": 16000},
        )
        self.assertEqual(configured_request.interviewer_type, "video_person")
        self.assertTrue(configured_request.camera_settings["enabled"])
        self.assertEqual(configured_request.audio_settings["sample_rate"], 16000)


class InterviewMetadataPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.add = MagicMock()
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()

    async def test_session_configuration_is_written_by_crud(self):
        interview = await create_interview(
            self.db,
            InterviewCreate(
                job_id="job-3",
                persona_config={"name": "Avery"},
                session_metadata={"client": "web"},
                interviewer_type="video_person",
                camera_settings={"enabled": True},
                audio_settings={"enabled": True},
            ),
            user_id=4,
        )
        self.assertEqual(interview.persona_config, {"name": "Avery"})
        self.assertEqual(interview.session_metadata, {"client": "web"})
        self.assertEqual(interview.interviewer_type, "video_person")
        self.assertEqual(interview.camera_settings, {"enabled": True})
        self.assertEqual(interview.audio_settings, {"enabled": True})

    async def test_message_metadata_is_written_by_crud(self):
        message = await create_interview_message(
            self.db,
            9,
            InterviewMessageCreate(
                role="assistant",
                content="Hello",
                avatar_style="warm",
                avatar_id="avatar-1",
                video_url="https://example.test/video.mp4",
                video_status="ready",
                response_mode="video",
                speaking_state="speaking",
            ),
        )
        self.assertIsInstance(message, InterviewMessage)
        self.assertEqual(message.avatar_style, "warm")
        self.assertEqual(message.avatar_id, "avatar-1")
        self.assertEqual(message.video_url, "https://example.test/video.mp4")
        self.assertEqual(message.ai_avatar_video_url, message.video_url)
        self.assertEqual(message.video_status, "ready")
        self.assertEqual(message.response_mode, "video")
        self.assertEqual(message.speaking_state, "speaking")


if __name__ == "__main__":
    unittest.main()
