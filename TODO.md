# Resume Analysis Fix Progress

## Status: In Progress

### TODO (Step-by-step)
- [ ] 1. Install deps: pip install pdfplumber json-repair
- [ ] 2. Edit app/routers/resumes.py (PDF extraction)
- [ ] 3. Edit app/services/ai_analysis.py (parsing, fallback, logging)
- [ ] 4. Edit app/models/resume.py + schemas/resume.py (add analysis_result)
- [ ] 5. Create Alembic migration
- [ ] 6. Edit app/routers/analysis.py (store in model)
- [ ] 7. Update requirements.txt
- [ ] 8. Run alembic upgrade head
- [ ] 9. Test endpoints
- [ ] 10. Verify with check_ scripts

## Next Step
Starting with step 1: Install dependencies.


