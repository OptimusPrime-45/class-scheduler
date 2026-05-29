"""Database clean-up utility to truncate all tables.

Run from the backend/ directory to clean the database.
"""

from __future__ import annotations

import asyncio
from sqlalchemy import text

from app.db import Base, SessionLocal, engine
import app.models  # Force-register tables in SQLAlchemy metadata


async def truncate_all() -> None:
    print("Database: connecting to truncate...")
    async with SessionLocal() as session:
        # Get all registered tables sorted by dependency
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        if not tables:
            print("Database: No tables found in metadata.")
            return
        
        print(f"Database: truncating tables: {tables}")
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
        print("Database: successfully cleared all rows & restarted identities.")


async def main() -> None:
    try:
        await truncate_all()
    except Exception as e:
        print(f"Database clean failed: {type(e).__name__}: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
