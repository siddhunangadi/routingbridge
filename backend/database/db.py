"""Database engine + session setup.

No repository layer, no unit-of-work pattern — routers use `get_db()`
as a FastAPI dependency and talk to SQLAlchemy directly. Works against
either SQLite (local dev default) or Postgres/Supabase (set DATABASE_URL
to a postgresql+psycopg:// URL) — nothing else in the app is
database-specific, since every model uses plain SQLAlchemy types.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.utils.config import get_settings

settings = get_settings()

# check_same_thread=False is required for SQLite when accessed from FastAPI's
# threadpool-backed sync endpoints; safe here since each request gets its own
# session. Postgres has no such restriction, so this only applies to SQLite.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
