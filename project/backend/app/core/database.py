"""
SQLAlchemy engine / session setup for the local SQLite database.
No cloud database is ever used - DATABASE_URL defaults to a local
sqlite file under backend/database/app.db.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates all tables that don't exist yet. Safe to call on every startup."""
    # Import models so they're registered on Base.metadata before create_all.
    from app.models import user, camera, detection, alert, settings as settings_model, video_job  # noqa: F401
    Base.metadata.create_all(bind=engine)
