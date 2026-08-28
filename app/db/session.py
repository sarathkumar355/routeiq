"""
Database connection and session management.

Phase 1 scope: only the connection/session plumbing. No models, no tables —
those arrive in the schema-design phase. The engine is created lazily so
importing this module never fails even if DATABASE_URL isn't set yet.
"""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Create (once) and return the SQLAlchemy engine.

    Raises a clear error if DATABASE_URL isn't configured, rather than
    failing with an opaque SQLAlchemy error.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Configure it in your .env file "
                "to use the database layer."
            )
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker:
    """Create (once) and return the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False
        )
    return _SessionLocal


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context-managed session — use as `with get_db_session() as db: ...`."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """Run a trivial query to confirm the database is reachable.

    Returns True/False rather than raising, so callers (like /health checks
    or tests) can decide how to react.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
