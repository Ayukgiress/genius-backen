# Mediapipe Update TODO

**Completed:**
- [x] Update requirements.txt: mediapipe==0.10.14 -> mediapipe==0.10.30
- [x] Created TODO.md tracking

**Completed:**
- [x] Local deps verify (externally-managed env; deps will install on deploy)
- [x] requirements.txt fixed for mediapipe

**Next steps for deploy success:**
- [ ] git add . && git commit -m "fix: update mediapipe to 0.10.30 for deploy" && git push
- [ ] Redeploy on Render/Railway/etc.
- [ ] Test MediaPipe interview features

**New issue noted (separate from mediapipe):**
CORS/502 on /auth/token - check server logs, CORS config (app/routers/auth.py, app/core/config.py?)
