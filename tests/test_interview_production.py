import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost/test_db",
)

from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.crud.interview import (
    create_interview,
    create_interview_message,
    create_interview_turn_messages,
    get_interview_messages,
)
from app.routers.interviews import (
    create_new_interview,
    get_messages,
    interview_talk_websocket,
)
from app.schemas.interview import (
    InterviewAudioMessageCreate,
    InterviewCreate,
    InterviewMessageCreate,
)
from app.services.interview import InterviewService


class InterviewRequestValidationTests(unittest.TestCase):
    def test_create_interview_rejects_blank_job_id(self):
        with self.assertRaises(ValidationError):
            InterviewCreate(job_id="   ")

    def test_message_requires_nonempty_content(self):
        with self.assertRaises(ValidationError):
            InterviewMessageCreate(role="user", content="   ")

    def test_audio_request_rejects_empty_payload(self):
        with self.assertRaises(ValidationError):
            InterviewAudioMessageCreate(base64_audio="  ")


class InterviewWriteSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_interview_rolls_back_on_commit_failure(self):
        db = MagicMock()
        db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        db.commit.side_effect = RuntimeError("database unavailable")
        with self.assertLogs("app.crud.interview", level="ERROR"):
            with self.assertRaises(RuntimeError):
                await create_interview(db, InterviewCreate(job_id="job-1"), user_id=4)
        db.rollback.assert_awaited_once()

    async def test_create_message_rolls_back_on_commit_failure(self):
        db = MagicMock()
        db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        db.commit.side_effect = RuntimeError("database unavailable")
        with self.assertLogs("app.crud.interview", level="ERROR"):
            with self.assertRaises(RuntimeError):
                await create_interview_message(
                    db,
                    7,
                    InterviewMessageCreate(role="user", content="Hello"),
                )
        db.rollback.assert_awaited_once()

    async def test_turn_messages_are_saved_atomically(self):
        db = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        user_message = InterviewMessageCreate(role="user", content="My answer")
        assistant_message = InterviewMessageCreate(role="assistant", content="Next question")

        saved_user, saved_assistant = await create_interview_turn_messages(
            db, 7, user_message, assistant_message, transcript="My answer"
        )

        self.assertEqual(saved_user.role, "user")
        self.assertEqual(saved_assistant.role, "assistant")
        db.add_all.assert_called_once()
        self.assertEqual(len(db.add_all.call_args.args[0]), 2)
        db.commit.assert_awaited_once()
        self.assertEqual(db.refresh.await_count, 2)

    async def test_turn_message_commit_failure_rolls_back_both_messages(self):
        db = MagicMock()
        db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
        db.refresh = AsyncMock()
        db.rollback = AsyncMock()
        with self.assertLogs("app.crud.interview", level="ERROR"):
            with self.assertRaises(RuntimeError):
                await create_interview_turn_messages(
                    db,
                    7,
                    InterviewMessageCreate(role="user", content="My answer"),
                    InterviewMessageCreate(role="assistant", content="Next question"),
                    transcript="My answer",
                )
        db.rollback.assert_awaited_once()

    async def test_get_messages_returns_ordered_result_set(self):
        expected = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: expected))
        db = AsyncMock()
        db.execute.return_value = result

        messages = await get_interview_messages(db, 3)

        self.assertEqual(messages, expected)
        db.execute.assert_awaited_once()


class InterviewEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_interview_generates_and_persists_initial_message(self):
        interview = SimpleNamespace(
            id=5,
            user_id=12,
            job_id="job-5",
            status="started",
        )
        saved_message = SimpleNamespace(id=20)
        db = AsyncMock()
        user = SimpleNamespace(id=12)
        response = Response()

        with (
            patch(
                "app.routers.interviews.get_or_create_interview",
                new_callable=AsyncMock,
                return_value=(interview, True),
            ),
            patch("app.routers.interviews._set_session_state", new_callable=AsyncMock),
            patch(
                "app.routers.interviews.interview_service.start_interview",
                new_callable=AsyncMock,
                return_value={"initial_message": "Welcome to the interview."},
            ),
            patch(
                "app.routers.interviews.create_interview_message",
                new_callable=AsyncMock,
                return_value=saved_message,
            ),
            patch("app.routers.interviews.track_interview_event", new_callable=AsyncMock) as track,
        ):
            result = await create_new_interview(
                InterviewCreate(job_id="job-5"), response, db, user
            )

        self.assertIs(result, interview)
        self.assertEqual(interview.status, "waiting_for_user")
        self.assertTrue(interview.session_created)
        self.assertEqual(interview.messages, [saved_message])
        event_names = [call.kwargs["event_type"] for call in track.await_args_list]
        self.assertEqual(event_names, ["interview_started", "question_generated"])

    async def test_get_messages_checks_owner_and_returns_messages(self):
        interview = SimpleNamespace(id=8)
        expected = [SimpleNamespace(id=2)]
        with (
            patch(
                "app.routers.interviews._get_owned_interview",
                new_callable=AsyncMock,
                return_value=interview,
            ),
            patch(
                "app.routers.interviews.get_interview_messages",
                new_callable=AsyncMock,
                return_value=expected,
            ),
        ):
            result = await get_messages(8, AsyncMock(), SimpleNamespace(id=12))
        self.assertEqual(result, expected)

    async def test_malformed_audio_returns_structured_error(self):
        service = InterviewService.__new__(InterviewService)
        service.groq_client = object()
        result = await service.handle_audio_turn("%%%bad-base64%%%", "job-1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "decode")
        self.assertEqual(result["error"], "Audio payload is not valid base64.")

    async def test_empty_content_is_valid_for_structured_error_responses(self):
        from app.schemas.interview import InterviewMessageResponse

        response = InterviewMessageResponse(
            id=-1,
            interview_id=7,
            role="assistant",
            content="",
            status="error",
            error="Audio could not be processed.",
        )
        self.assertEqual(response.content, "")


class InterviewVideoFrameValidationTests(unittest.TestCase):
    def test_rejects_malformed_video_base64(self):
        from app.services.interview import VideoPayloadError

        with self.assertRaises(VideoPayloadError) as raised:
            InterviewService._decode_video_frame_payload("%%%bad-base64%%")
        self.assertEqual(raised.exception.category, "decode")

    def test_accepts_supported_image_data_url(self):
        import base64

        image_bytes = b"test-image-bytes"
        payload = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        self.assertEqual(
            InterviewService._decode_video_frame_payload(payload),
            image_bytes,
        )


class WebSocketAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_token_returns_stable_auth_error_and_closes(self):
        database = object()
        websocket = SimpleNamespace(
            accept=AsyncMock(),
            receive_json=AsyncMock(return_value={"type": "auth", "token": "invalid-token"}),
            send_json=AsyncMock(),
            close=AsyncMock(),
        )

        async def db_dependency():
            yield database

        with (
            patch("app.routers.interviews.get_db", new=db_dependency),
            patch(
                "app.routers.interviews.get_user_from_token",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=401, detail="invalid"),
            ),
        ):
            await interview_talk_websocket(websocket, 6)

        websocket.send_json.assert_awaited_once_with({
            "error": "Invalid authentication token.",
            "status": "error",
            "error_type": "authentication",
        })
        websocket.close.assert_awaited_once_with(code=1008)

    async def test_missing_auth_fields_are_rejected_before_database_access(self):
        websocket = SimpleNamespace(
            accept=AsyncMock(),
            receive_json=AsyncMock(return_value={"type": "auth"}),
            send_json=AsyncMock(),
            close=AsyncMock(),
        )
        with patch("app.routers.interviews.get_db") as get_db_mock:
            await interview_talk_websocket(websocket, 6)
        get_db_mock.assert_not_called()
        sent = websocket.send_json.await_args.args[0]
        self.assertEqual(sent["error_type"], "authentication")
        self.assertEqual(sent["status"], "error")
        websocket.close.assert_awaited_once_with(code=1008)


if __name__ == "__main__":
    unittest.main()
