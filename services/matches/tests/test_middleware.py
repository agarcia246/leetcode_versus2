import logging

import pytest
from fastapi.testclient import TestClient

from app.config import CORS_ORIGINS
from app.database import get_db
from app.main import app

UI_ORIGIN = CORS_ORIGINS[0]  # http://localhost:8080 unless CORS_ORIGINS is set
OTHER_ORIGIN = "https://evil.example.com"


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_ui_origin_is_allowed(client):
    response = client.get("/rooms/NOPE00", headers={"Origin": UI_ORIGIN})

    assert response.headers["access-control-allow-origin"] == UI_ORIGIN


def test_any_other_origin_is_not_allowed(client):
    response = client.get("/rooms/NOPE00", headers={"Origin": OTHER_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_a_json_post_allows_content_type(client):
    # A POST with a JSON body makes the browser ask first, with OPTIONS.
    response = client.options(
        "/rooms/create",
        headers={
            "Origin": UI_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "POST" in response.headers["access-control-allow-methods"]


def test_preflight_from_another_origin_is_refused(client):
    response = client.options(
        "/rooms/create",
        headers={
            "Origin": OTHER_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_every_request_logs_method_path_status_and_duration(client, caplog):
    with caplog.at_level(logging.INFO, logger="matches"):
        client.get("/rooms/NOPE00")

    lines = [record.getMessage() for record in caplog.records if record.name == "matches"]
    assert len(lines) == 1
    method, path, status, duration = lines[0].split()
    assert (method, path, status) == ("GET", "/rooms/NOPE00".split("?")[0], "404")
    assert duration.endswith("ms") and float(duration[:-2]) >= 0
