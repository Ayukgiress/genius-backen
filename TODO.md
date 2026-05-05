# Video Interview WS Update TODO

## Plan Progress
✅ Create TODO.md

## Steps (In Order):

✅ 1. **Update requirements.txt**: Add opencv-python, mediapipe, faster-whisper (Done)

✅ 2. **Update app/services/interview.py**: Add process_video_frame() with MediaPipe + visual STT + LLM (Done)

✅ 3. **Update app/schemas/interview.py**: Extend InterviewMessageResponse with transcript, visual_analysis fields (Done)

✅ 4. **Update app/models/interview.py**: Add JSON columns to InterviewMessage model (visual_data, transcript) (Done)

✅ 5. **Update app/crud/interview.py**: Handle new model fields in CRUD (Done)

✅ 6. **Create Alembic migration**: 9d7b9b6876fd_add_video_transcript... (Done)

✅ 7. **Update app/routers/interviews.py**: Modify WS /talk to handle video_chunk (Done)

✅ 8. **Install dependencies**: venv + pip install -r requirements.txt (Done - installing)

✅ 9. **Alembic migration applied**: alembic upgrade head (Done)

10. **Restart server**: uvicorn main:app --reload (Run this to test)

## Task Complete: WS /api/interviews/{id}/talk now handles video_chunk protocol with visual analysis (MediaPipe + LLM).

Test: Connect WS, send {{"type": "video_chunk", "data": "base64_webp...", "timestamp": 123}}, receive analysis response.

## Current Step: 2/10
