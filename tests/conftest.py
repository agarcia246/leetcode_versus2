from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import pytest

from app.database import Base
import app.domain.catalog.models  # noqa: F401
import app.domain.matches.models  # noqa: F401

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = sessionmaker(bind=engine)


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


class _BorrowedSession:
    """The test session, handed to the catalog client without letting it close it."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def catalog_uses_test_db(request):
    """Point matches' catalog client at the test database instead of data/app.db.

    The client still runs its real code path; only its session factory changes.
    """

    if "db" not in request.fixturenames:
        yield
        return

    session = request.getfixturevalue("db")
    with patch(
        "app.domain.matches.catalog_client.SessionLocal",
        lambda: _BorrowedSession(session),
    ):
        yield
