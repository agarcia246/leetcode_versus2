import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models import (
    CreateRoomModel,
    GetRoomModel,
    JoinRoomModel,
    Player,
    Room,
    RoomPlayer,
    RoomProblem,
    StartRoomModel,
)
from app.services import create_room, get_room, join_room, start_room
import responses

from app import config
from app.catalog_client import CatalogUnavailable
from tests.factories import TWO_SUM, add_player, add_room, attach, seat


def host_model(username="alex"):
    return CreateRoomModel(
        host_username=username,
        duration=30,
        difficulty="Easy",
        topics=["Array"],
        problem_count=2,
    )


PICKED = [
    {"id": 7, "title": "Two Sum", "slug": "two-sum", "url": "u", "difficulty": "Easy"},
    {"id": 3, "title": "Valid Parentheses", "slug": "valid-parentheses", "url": "u", "difficulty": "Easy"},
]


@patch("app.services.lookup_leetcode_user", return_value="alex")
@patch("app.services.catalog_client.pick_problems", return_value=PICKED)
def test_create_room_deals_the_problems_the_catalog_picked(mock_pick, mock_lookup, db):
    result = create_room(db, host_model())

    assert result["room_code"] is not None
    assert result["host_id"] is not None
    mock_pick.assert_called_once_with(count=2, topics=["Array"], difficulty="Easy")
    dealt = (
        db.query(RoomProblem)
        .filter(RoomProblem.room_id == result["room_id"])
        .order_by(RoomProblem.display_order)
        .all()
    )
    assert [(row.problem_id, row.display_order) for row in dealt] == [(7, 0), (3, 1)]


@patch("app.services.catalog_client.pick_problems", side_effect=ValueError("Not enough problems"))
@patch("app.services.lookup_leetcode_user", return_value="alex")
def test_create_room_writes_nothing_when_the_catalog_refuses(mock_lookup, mock_pick, db):
    with pytest.raises(ValueError, match="Not enough problems"):
        create_room(db, host_model())

    assert db.query(Room).count() == 0
    assert db.query(Player).count() == 0
    mock_lookup.assert_not_called()


@patch("app.services.catalog_client.pick_problems", return_value=PICKED[:1])
@patch("app.services.lookup_leetcode_user", return_value="alex")
def test_create_room_rejects_a_short_problem_set(mock_lookup, mock_pick, db):
    with pytest.raises(ValueError, match="Not enough problems"):
        create_room(db, host_model())

    assert db.query(Room).count() == 0


CATALOG = "http://catalog.test"
CONTAINS_DUPLICATE = {
    "id": 2,
    "title": "Contains Duplicate",
    "slug": "contains-duplicate",
    "url": "https://leetcode.com/problems/contains-duplicate/",
    "difficulty": "Easy",
}


@responses.activate
@patch.object(config, "CATALOG_URL", CATALOG)
@patch("app.services.lookup_leetcode_user", return_value="alex")
def test_create_then_get_room_across_the_seam(mock_lookup, db):
    """Matches -> HTTP -> catalog, with the catalog service replaced by a stub."""

    pick = responses.post(f"{CATALOG}/problems/pick", json=[TWO_SUM, CONTAINS_DUPLICATE])
    lookup = responses.get(f"{CATALOG}/problems", json=[TWO_SUM, CONTAINS_DUPLICATE])

    created = create_room(db, host_model())
    state = get_room(db, GetRoomModel(room_code=created["room_code"]))

    assert pick.call_count == 1
    assert json.loads(pick.calls[0].request.body) == {"count": 2, "topics": ["Array"], "difficulty": "Easy"}
    assert lookup.calls[0].request.params == {"ids": "1,2"}
    assert [problem["slug"] for problem in state["problems"]] == ["two-sum", "contains-duplicate"]
    assert [problem["display_order"] for problem in state["problems"]] == [0, 1]
    assert state["problems_unavailable"] is False


def test_join_room_paths(db):
    host = add_player(db, "alex")
    created = datetime.now(timezone.utc) - timedelta(hours=2)
    room = add_room(db, host, created=created)
    seat(db, room, host)

    with patch("app.services.lookup_leetcode_user", return_value="sam"):
        with pytest.raises(HTTPException) as inactive:
            join_room(db, JoinRoomModel(username="sam", room_code="room01"))
    assert inactive.value.status_code == 400
    assert inactive.value.detail == "Room is inactive"

    fresh = add_room(db, host, code="FRESH1")
    seat(db, fresh, host)
    with patch("app.services.lookup_leetcode_user", return_value="sam"):
        joined = join_room(db, JoinRoomModel(username="sam", room_code="fresh1"))
    assert joined["player_id"] is not None

    with patch("app.services.lookup_leetcode_user", return_value="sam"):
        again = join_room(db, JoinRoomModel(username="sam", room_code="FRESH1"))
    assert again["player_id"] == joined["player_id"]

    with pytest.raises(HTTPException) as missing:
        join_room(db, JoinRoomModel(username="sam", room_code="NOPE00"))
    assert missing.value.status_code == 404

    finished = add_room(db, host, code="DONE01", status="Finished")
    with pytest.raises(HTTPException) as done:
        join_room(db, JoinRoomModel(username="sam", room_code="DONE01"))
    assert done.value.detail == "Room already finished"

    live = add_room(db, host, code="LIVE01", status="Active")
    with patch("app.services.lookup_leetcode_user", return_value="late"):
        late = join_room(db, JoinRoomModel(username="late", room_code="LIVE01"))
    seated = db.query(RoomPlayer).filter(RoomPlayer.player_id == late["player_id"]).one()
    assert seated.result == "In_Progress"

    with patch("app.services.get_or_create_player", side_effect=RuntimeError("db down")):
        with pytest.raises(RuntimeError, match="db down"):
            join_room(db, JoinRoomModel(username="sam", room_code="FRESH1"))


def test_start_room_paths(db):
    host = add_player(db, "alex")
    guest = add_player(db, "sam")
    created = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = add_room(db, host, code="OLD001", created=created)
    seat(db, expired, host)
    seat(db, expired, guest)
    db.commit()

    with pytest.raises(HTTPException) as inactive:
        start_room(db, StartRoomModel(player_id=host.id, room_code="OLD001"))
    assert inactive.value.detail == "Room is inactive"

    waiting = add_room(db, host, code="WAIT01")
    seat(db, waiting, host)
    db.commit()
    with pytest.raises(HTTPException) as alone:
        start_room(db, StartRoomModel(player_id=host.id, room_code="WAIT01"))
    assert alone.value.detail == "Need at least 2 players"

    seat(db, waiting, guest)
    db.commit()
    with pytest.raises(HTTPException) as empty:
        start_room(db, StartRoomModel(player_id=host.id, room_code="WAIT01"))
    assert empty.value.detail == "No problems in room"

    with pytest.raises(HTTPException) as stranger:
        start_room(db, StartRoomModel(player_id=guest.id, room_code="WAIT01"))
    assert stranger.value.detail == "Host must start room"

    attach(db, waiting, TWO_SUM["id"])
    db.commit()
    started = start_room(db, StartRoomModel(player_id=host.id, room_code="wait01"))
    assert started["message"] == "Room started"
    assert db.get(Room, waiting.id).current_status == "Active"

    with pytest.raises(HTTPException) as twice:
        start_room(db, StartRoomModel(player_id=host.id, room_code="WAIT01"))
    assert twice.value.detail == "Room already started"

    with pytest.raises(HTTPException) as missing:
        start_room(db, StartRoomModel(player_id=host.id, room_code="NOPE00"))
    assert missing.value.status_code == 404

    boom = add_room(db, host, code="BOOM01")
    seat(db, boom, host)
    seat(db, boom, guest)
    attach(db, boom, TWO_SUM["id"])
    db.commit()
    with patch("app.services.utc_now", side_effect=[datetime.now(timezone.utc), RuntimeError("clock")]):
        with pytest.raises(RuntimeError, match="clock"):
            start_room(db, StartRoomModel(player_id=host.id, room_code="BOOM01"))


def test_get_room_polls_scores_and_finishes(db):
    with pytest.raises(HTTPException) as missing:
        get_room(db, GetRoomModel(room_code="NOPE00"))
    assert missing.value.status_code == 404

    now = datetime.now(timezone.utc)
    host = add_player(db, "alex")
    guest = add_player(db, "sam")
    room = add_room(
        db,
        host,
        code="LIVE01",
        status="Active",
        start=now - timedelta(minutes=5),
        end=now + timedelta(minutes=25),
    )
    host_seat = seat(db, room, host, result="In_Progress")
    seat(db, room, guest, result="In_Progress")
    attach(db, room, TWO_SUM["id"])
    db.commit()

    accepted = {
        "titleSlug": "two-sum",
        "timestamp": int((now - timedelta(minutes=1)).timestamp()),
        "statusDisplay": "Accepted",
    }

    def submissions(username):
        if username == "alex":
            return {"submissions": [accepted], "hidden": False}
        raise RuntimeError("timeout")

    with patch("app.services.get_leetcode_player_submissions", side_effect=submissions):
        with patch("app.services.catalog_client.get_problems", return_value=[TWO_SUM]):
            state = get_room(db, GetRoomModel(room_code="live01"))

    assert state["status"] == "Active"
    assert state["problems"][0]["slug"] == "two-sum"
    scores = {player["username"]: player["score"] for player in state["players"]}
    assert scores["alex"] == 1
    assert "sam: timeout" in db.get(Room, room.id).poll_error

    hidden = add_room(db, host, code="HIDE01", status="Active", start=now - timedelta(minutes=5), end=now + timedelta(minutes=10))
    seat(db, hidden, host, result="In_Progress")
    with patch(
        "app.services.get_leetcode_player_submissions",
        return_value={"submissions": [], "hidden": True},
    ):
        get_room(db, GetRoomModel(room_code="HIDE01"))
    assert "private" in db.get(Room, hidden.id).poll_error

    over = add_room(
        db,
        host,
        code="OVER01",
        status="Active",
        start=now - timedelta(minutes=40),
        end=now - timedelta(minutes=1),
    )
    seat(db, over, host, score=2, result="In_Progress")
    seat(db, over, guest, score=2, result="In_Progress")
    with patch(
        "app.services.get_leetcode_player_submissions",
        return_value={"submissions": [], "hidden": False},
    ):
        finished = get_room(db, GetRoomModel(room_code="OVER01"))
    assert finished["status"] == "Finished"
    assert {player["result"] for player in finished["players"]} == {"Winner"}

    pending = add_room(db, host, code="PEND01", status="Finished", end=now - timedelta(minutes=1))
    seat(db, pending, host, score=0, result="In_Progress")
    with patch(
        "app.services.get_leetcode_player_submissions",
        return_value={"submissions": [], "hidden": False},
    ):
        closed = get_room(db, GetRoomModel(room_code="PEND01"))
    assert closed["players"][0]["result"] == "Loser"

    stale = add_room(db, host, code="STALE1", created=now - timedelta(hours=2))
    seat(db, stale, host)
    stale_state = get_room(db, GetRoomModel(room_code="STALE1"))
    assert stale_state["status"] == "Inactive"

    broken = add_room(db, host, code="BROKE1", status="Active", start=now - timedelta(minutes=5), end=now + timedelta(minutes=10))
    seat(db, broken, host, result="In_Progress")
    db.commit()
    with patch("app.services.get_leetcode_player_submissions", side_effect=ValueError("boom")):
        with pytest.raises(ValueError, match="boom"):
            get_room(db, GetRoomModel(room_code="BROKE1"))
    assert db.get(Room, broken.id).poll_error == "boom"
    assert host_seat.score == 1


def test_get_room_degrades_when_the_catalog_is_unavailable(db):
    now = datetime.now(timezone.utc)
    host = add_player(db, "alex")
    guest = add_player(db, "sam")
    room = add_room(
        db,
        host,
        code="LIVE01",
        status="Active",
        start=now - timedelta(minutes=5),
        end=now + timedelta(minutes=25),
    )
    seat(db, room, host, score=1, result="In_Progress")
    seat(db, room, guest, score=0, result="In_Progress")
    attach(db, room, TWO_SUM["id"])
    db.commit()

    with patch("app.services.catalog_client.get_problems", side_effect=CatalogUnavailable()):
        with patch("app.services.get_leetcode_player_submissions") as poll:
            state = get_room(db, GetRoomModel(room_code="LIVE01"))

    # The room still loads: players and scores come from matches' own database.
    assert state["status"] == "Active"
    assert {player["username"]: player["score"] for player in state["players"]} == {"alex": 1, "sam": 0}
    # Problem details live in the catalog, so they are missing and flagged.
    assert state["problems"] == []
    assert state["problems_unavailable"] is True
    # Scoring needs the catalog's slugs, so this round of polling is skipped.
    poll.assert_not_called()
    assert db.get(Room, room.id).last_polled_at is None
    assert db.get(Room, room.id).poll_error is None


def test_a_room_without_problems_never_calls_the_catalog(db):
    host = add_player(db, "alex")
    room = add_room(db, host, code="EMPTY1")
    seat(db, room, host)
    db.commit()

    with patch("app.catalog_client.requests.request") as request:
        state = get_room(db, GetRoomModel(room_code="EMPTY1"))

    request.assert_not_called()
    assert state["problems"] == []
    assert state["problems_unavailable"] is False
