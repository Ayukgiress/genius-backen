import asyncio, importlib, os, pkgutil
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
import app.models

for m in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{m.name}")
from app.db.session import Base


async def main():
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        connect_args={"statement_cache_size": 0},
    )

    def diff(sync_conn):
        insp = inspect(sync_conn)
        existing = set(insp.get_table_names())
        for t in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
            if t.name not in existing:
                print(f"-- MISSING TABLE: {t.name}")
                continue
            have = {c["name"] for c in insp.get_columns(t.name)}
            for c in t.columns:
                if c.name not in have:
                    typ = c.type.compile(dialect=sync_conn.dialect)
                    print(f'ALTER TABLE "{t.name}" ADD COLUMN IF NOT EXISTS "{c.name}" {typ};')

    async with engine.connect() as conn:
        await conn.run_sync(diff)
    await engine.dispose()


asyncio.run(main())
