# Fix Job Recommendations Error Handling and Manual Plan Update

Status: COMPLETE ✅

## Recent Changes:
- [x] Updated /jobs/recommendations and /jobs/{job_id}/match to return structured responses instead of 403 errors when limit reached
- [x] Added POST /debug/update-plan to manually set subscription plan (temporary)
- [x] Updated TODO.md

## Steps (from previous):
- [x] 1. Update app/schemas/user.py - Added subscription fields ✅
- [x] 2. Update app/routers/payment.py - Added auto-reset of job_matching usage on Pro upgrade ✅
- [x] 3. Created app/routers/debug.py - GET /api/debug/user-status to check your status ✅
- [x] 4. Added debug logging to app/routers/jobs.py ✅
- [x] 5. Updated TODO.md ✅

## Verification:
**Restart server:**
```
cd /home/giress/projects/genius && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Check your status:**
1. Visit `http://127.0.0.1:8000/api/debug/user-status` (login required)
2. If still showing "free", POST to `http://127.0.0.1:8000/api/debug/update-plan` with body `{"plan": "pro"}`
3. Check server console logs for "[DEBUG] User X: plan=pro"
4. Test `http://127.0.0.1:8000/api/jobs/recommendations?resume_id=4` - should return recommendations without error

**Frontend Update Needed:** Update frontend to handle new response format - check for `limit_reached` flag and show message instead of throwing error.

**Future Upgrades:** Usage auto-resets to 0 on payment success. Remove /debug after testing.

Task complete - Error handling improved and manual fix available!

