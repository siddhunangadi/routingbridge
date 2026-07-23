"""SQLite engine + session setup.

No repository layer, no unit-of-work pattern — this is a single-table
app. Routers use `get_db()` as a FastAPI dependency and talk to
SQLAlchemy directly, which is honest about how small this app is.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.utils.config import get_settings

settings = get_settings()

# check_same_thread=False is required for SQLite when accessed from FastAPI's
# threadpool-backed sync endpoints; safe here since each request gets its own session.
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
