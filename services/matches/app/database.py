"""Engine and session for this service's own database (DATABASE_URL)."""

import logging
import time

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # drop pooled connections that died while the DB was paused
    connect_args={"login_timeout": 10} if DATABASE_URL.startswith("mssql") else {},
)

logger = logging.getLogger(__name__)
SessionLocal = sessionmaker(engine)
Base = declarative_base()


def wait_for_db(attempts: int = 10, first_delay: float = 2.0, max_delay: float = 20.0) -> None:
    delay = first_delay
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            logger.warning("database not ready (attempt %d/%d): %s; retrying in %.0fs",
                           attempt, attempts, exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, max_delay)


def get_db():
    """FastAPI dependency: one session per request."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
