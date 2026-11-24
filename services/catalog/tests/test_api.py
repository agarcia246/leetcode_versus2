from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.factories import add_problem


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)  # not a context manager: the lifespan (init_db) is not run
    app.dependency_overrides.clear()


def test_get_problems_returns_known_ids_in_order(client, db):
    first = add_problem(db, slug="two-sum", title="Two Sum")
    second = add_problem(db, slug="valid-parentheses", title="Valid Parentheses")
    db.commit()

    response = client.get("/problems", params={"ids": f"{second.id},999,{first.id}"})

    assert response.status_code == 200
    assert [problem["slug"] for problem in response.json()] == ["valid-parentheses", "two-sum"]
    assert set(response.json()[0]) == {"id", "title", "slug", "url", "difficulty"}


def test_get_problems_rejects_bad_ids_and_accepts_none(client):
    assert client.get("/problems", params={"ids": "1,x"}).status_code == 400
    assert client.get("/problems").json() == []


def test_pick_problems_maps_errors_to_status_codes(client):
    body = {"count": 2, "topics": ["Array"], "difficulty": "Easy"}

    with patch("app.router.pick_problems", return_value=[]):
        assert client.post("/problems/pick", json=body).json() == []

    with patch("app.router.pick_problems", side_effect=ValueError("Not enough problems available for selection")):
        refused = client.post("/problems/pick", json=body)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Not enough problems available for selection"

    with patch("app.router.pick_problems", side_effect=RuntimeError("LeetCode API error: down")):
        assert client.post("/problems/pick", json=body).status_code == 502

    assert client.post("/problems/pick", json={"count": 2}).status_code == 422


def test_filters_route(client):
    tags = [{"name": "Array", "slug": "array"}]
    with patch("app.services.fetch_topic_tags", return_value=tags):
        response = client.get("/filters")
    assert response.json() == {"difficulties": ["Easy", "Medium", "Hard"], "topics": tags}

    with patch("app.services.fetch_topic_tags", side_effect=RuntimeError("LeetCode API error: down")):
        assert client.get("/filters").status_code == 502
