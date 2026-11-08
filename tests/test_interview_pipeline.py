import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_db",
)

from app.routers.interviews import _process_audio_conversation_turn
from app.schemas.interview import InterviewMessageResponse


class SharedInterviewAudioPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.interview = SimpleNamespace(
            id=12, user_id=42, job_id="job-1", status="active"
        )

    async def test_success_response_has_transport_neutral_aliases(self):
        saved_ai_message = SimpleNamespace(
            id=24,
            interview_id=12,
            role="assistant",
            content="Tell me about your experience.",
            transcript="I led a team.",
            audio_data="generated-audio",
            visual_data=None,
            created_at=None,
        )
        with (
            patch("app.routers.interviews._set_session_state", new_callable=AsyncMock),
            patch("app.routers.interviews.track_interview_event", new_callable=AsyncMock),
            patch(
                "app.routers.interviews.get_interview_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.routers.interviews.interview_service.handle_audio_turn",
                new_callable=AsyncMock,
                return_value={
                    "status": "success",
                    "transcript": "I led a team.",
                    "content": "Tell me about your experience.",
                    "ai_audio_data": "generated-audio",
                },
            ),
            patch(
                "app.routers.interviews.create_interview_turn_messages",
                new_callable=AsyncMock,
                return_value=(None, saved_ai_message),
            ),
        ):
            payload, http_status = await _process_audio_conversation_turn(
                AsyncMock(), self.interview, "audio-payload"
            )

        self.assertEqual(http_status, 200)
        self.assertEqual(payload["transcript"], "I led a team.")
        self.assertEqual(payload["ai_text"], "Tell me about your experience.")
        self.assertEqual(payload["ai_audio_base64"], "generated-audio")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["session_state"], "ai_speaking")
        # HTTP response validation must preserve the same compatibility aliases.
        serialized = InterviewMessageResponse(**payload).model_dump()
        self.assertEqual(serialized["ai_text"], payload["ai_text"])
        self.assertEqual(serialized["ai_audio_base64"], payload["ai_audio_base64"])

    async def test_no_speech_has_the_same_sentinel_shape(self):
        with (
            patch("app.routers.interviews._set_session_state", new_callable=AsyncMock),
            patch("app.routers.interviews.track_interview_event", new_callable=AsyncMock),
            patch(
                "app.routers.interviews.get_interview_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "app.routers.interviews.interview_service.handle_audio_turn",
                new_callable=AsyncMock,
                return_value={"status": "no_speech", "transcript": ""},
            ),
            patch(
                "app.routers.interviews.create_interview_turn_messages",
                new_callable=AsyncMock,
            ) as save_message,
        ):
            payload, http_status = await _process_audio_conversation_turn(
                AsyncMock(), self.interview, "silent-audio"
            )

        self.assertEqual(http_status, 200)
        self.assertEqual(payload["transcript"], "")
        self.assertEqual(payload["ai_text"], "")
        self.assertIsNone(payload["ai_audio_base64"])
        self.assertEqual(payload["status"], "no_speech")
        self.assertEqual(payload["session_state"], "no_speech")
        save_message.assert_not_awaited()

        # HTTP response validation must allow an empty content field for the
        # no_speech sentinel while retaining the canonical media contract.
        serialized = InterviewMessageResponse(**payload).model_dump()
        self.assertEqual(serialized["content"], "")
        self.assertEqual(serialized["transcript"], "")
        self.assertEqual(serialized["status"], "no_speech")


if __name__ == "__main__":
    unittest.main()
