"""Apply migrations/NNN_*.sql in order, each exactly once, recorded in schema_migrations."""

import logging
import re
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
GO_LINE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def run_migrations(engine, folder: Path = MIGRATIONS_DIR) -> list[str]:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "IF OBJECT_ID('schema_migrations') IS NULL "
            "CREATE TABLE schema_migrations ("
            " version NVARCHAR(255) PRIMARY KEY,"
            " applied_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
        )

    with engine.connect() as conn:
        applied = set(conn.execute(text("SELECT version FROM schema_migrations")).scalars())

    newly_applied = []
    for path in sorted(folder.glob("*.sql")):          # 001_ < 002_ < ... (zero-padded)
        if path.name in applied:
            continue
        with engine.begin() as conn:                     # one transaction per file
            for batch in GO_LINE.split(path.read_text()):
                if batch.strip():
                    conn.exec_driver_sql(batch)
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": path.name})
        logger.info("applied migration %s", path.name)  # the log line for the §4.6 evidence
        newly_applied.append(path.name)

    if not newly_applied:
        logger.info("no migrations to apply (%d already applied)", len(applied))
    return newly_applied