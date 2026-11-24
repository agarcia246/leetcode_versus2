"""Engine and session for this service's own database (DATABASE_URL)."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # sqlite:///data/matches.db -> make sure data/ exists before connecting.
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
)

SessionLocal = sessionmaker(engine)
Base = declarative_base()


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db():
    """FastAPI dependency: one session per request."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create this service's tables from schema.sql (SQLite only, until migrations replace it)."""

    connection = engine.raw_connection()
    try:
        connection.executescript(SCHEMA_PATH.read_text())
        connection.commit()
    finally:
        connection.close()
