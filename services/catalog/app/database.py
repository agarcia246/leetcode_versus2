"""Engine and session for this service's own database (DATABASE_URL)."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"login_timeout": 10} if DATABASE_URL.startswith("mssql") else {},
)

SessionLocal = sessionmaker(engine)
Base = declarative_base()




def get_db():
    """FastAPI dependency: one session per request."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

