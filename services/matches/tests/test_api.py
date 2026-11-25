from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.catalog_client import CatalogUnavailable
from app.database import get_db
from app.main import app
from tests.factories import TWO_SUM, add_player, add_room, attach, seat

NEW_ROOM = {
    "host_username": "alex",
    "duration": 30,
    "difficulty": "Easy",
    "topics": ["Array"],
    "problem_count": 2,
}


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)  # not a context manager: the lifespan (init_db) is not run
    app.dependency_overrides.clear()


def test_create_room_returns_503_when_the_catalog_is_unavailable(client):
    with patch("app.router.create_room", side_effect=CatalogUnavailable()):
        response = client.post("/rooms/create", json=NEW_ROOM)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The problem catalog is unavailable right now. Try again in a moment."
    }


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValueError("Not enough problems available for selection"), 400),
        (RuntimeError("Catalog service error 502: LeetCode API error"), 502),
    ],
)
def test_create_room_maps_other_errors(client, error, status):
    with patch("app.router.create_room", side_effect=error):
        response = client.post("/rooms/create", json=NEW_ROOM)

    assert response.status_code == status
    assert response.json()["detail"] == str(error)


def test_create_room_success_passes_the_result_through(client):
    created = {"room_code": "ABCDEF", "room_id": 1, "host_id": 1}
    with patch("app.router.create_room", return_value=created):
        response = client.post("/rooms/create", json=NEW_ROOM)

    assert response.status_code == 200
    assert response.json() == created


def test_get_room_over_http_degrades_when_the_catalog_is_unavailable(client, db):
    host = add_player(db, "alex")
    room = add_room(db, host, code="ROOM01")
    seat(db, room, host)
    attach(db, room, TWO_SUM["id"])
    db.commit()

    with patch("app.services.catalog_client.get_problems", side_effect=CatalogUnavailable()):
        response = client.get("/rooms/room01")

    assert response.status_code == 200
    body = response.json()
    assert body["problems_unavailable"] is True
    assert body["problems"] == []
    assert [player["username"] for player in body["players"]] == ["alex"]


def test_join_and_start_routes_reach_the_service(client):
    assert client.post("/rooms/NOPE00/join", json={"username": "sam"}).status_code == 404
    assert client.post("/rooms/NOPE00/start", json={"player_id": 1}).status_code == 404

    with patch("app.router.join_room", side_effect=ValueError("Username not found on LeetCode")):
        assert client.post("/rooms/ROOM01/join", json={"username": "x"}).status_code == 400

    with patch("app.router.join_room", side_effect=RuntimeError("LeetCode API error: down")):
        assert client.post("/rooms/ROOM01/join", json={"username": "x"}).status_code == 502
