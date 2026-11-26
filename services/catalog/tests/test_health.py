from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database import get_db, wait_for_db
from app.main import app
from app.models import HealthCheck


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)  # not a context manager: the lifespan is not run
    app.dependency_overrides.clear()


def test_health_ok(client, db):
    db.add(HealthCheck(id=1, checked_at=None))
    db.commit()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": "dev"}
    checked_at = db.get(HealthCheck, 1).checked_at
    assert checked_at is not None


def test_health_returns_503_when_execute_fails(client, db):
    error = OperationalError("database unavailable", "UPDATE health_check", {}, Exception("down"))
    with patch.object(db, "execute", side_effect=error):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "unavailable", "version": "dev"}


def test_wait_for_db_retries_then_succeeds():
    attempts = {"n": 0}
    ready = MagicMock()

    def connect():
        attempts["n"] += 1
        conn = MagicMock()
        if attempts["n"] <= 2:
            conn.__enter__.side_effect = OperationalError(
                "database not ready", "SELECT 1", {}, Exception("paused")
            )
        else:
            conn.__enter__.return_value = ready
        return conn

    with patch("app.database.engine.connect", side_effect=connect), patch("app.database.time.sleep") as sleep:
        wait_for_db()

    assert attempts["n"] == 3
    ready.exec_driver_sql.assert_called_once_with("SELECT 1")
    assert [call.args[0] for call in sleep.call_args_list] == [2.0, 4.0]
