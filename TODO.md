## TODO - Supabase PostgreSQL connection fixes

- [x] Update `app/db/session.py`
  - [x] Read `DATABASE_URL` via `os.getenv("DATABASE_URL")`
  - [x] Normalize `postgres://` / `postgresql://` -> `postgresql+asyncpg://`
  - [x] Use `create_async_engine` from `sqlalchemy.ext.asyncio`
  - [x] Add `connect_args={"ssl": "require"}`
  - [x] Keep `AsyncSession`, `sessionmaker`, and `Base` declaration intact
  - [x] Ensure `get_db` yields an `AsyncSession`

- [x] Update `app/main.py` startup
  - [x] Wrap entire `startup()` in try/except
  - [x] Add `print(f"DB URL: {engine.url}")` at start of startup
  - [x] Keep `Base.metadata.create_all` and ALTER TABLE statements
  - [x] Wrap `job_service.initialize()` in its own try/except


- [ ] Verify deployment startup logs on Render
  - [ ] Confirm no `[Errno -2] Name or service not known` during startup
  - [ ] Confirm DB connects successfully on first request

