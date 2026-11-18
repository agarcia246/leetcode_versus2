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
