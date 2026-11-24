from datetime import datetime, timedelta, timezone

from unittest.mock import patch

import pytest

from app.domain.matches.leetcode import (
    get_leetcode_player_submissions,
    leetcode_graphql,
    lookup_leetcode_user,
)
from app.domain.matches.models import Submission
from app.domain.matches.services import record_match_submissions
from tests.factories import add_player, add_problem, add_room, attach, seat


def open_match(db):
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    end = start + timedelta(minutes=30)
    host = add_player(db, "alex")
    room = add_room(db, host, status="Active", start=start, end=end)
    problem = add_problem(db)
    attach(db, room, problem)
    player = seat(db, room, host, result="In_Progress")
    return room, player, start, end, {problem.lc_id: problem.id}


def submission(slug, when, status):
    return {
        "titleSlug": slug,
        "timestamp": int(when.timestamp()),
        "statusDisplay": status,
    }


def test_get_leetcode_player_submissions_merges_and_hides():
    payload = {
        "data": {
            "recentSubmissionList": [
                {"titleSlug": "two-sum", "timestamp": "10", "statusDisplay": "Accepted"},
                {"titleSlug": None, "timestamp": "11", "statusDisplay": "Accepted"},
            ],
            "recentAcSubmissionList": [
                {"titleSlug": "two-sum", "timestamp": "10", "statusDisplay": "Accepted"},
                {"titleSlug": "two-sum", "timestamp": "12", "statusDisplay": "Accepted"},
            ],
        }
    }
    with patch("app.domain.matches.leetcode.leetcode_graphql", return_value=payload):
        merged = get_leetcode_player_submissions("alex")

    assert merged["hidden"] is False
    assert len(merged["submissions"]) == 2

    with patch(
        "app.domain.matches.leetcode.leetcode_graphql",
        return_value={"data": {"recentSubmissionList": None, "recentAcSubmissionList": None}},
    ):
        hidden = get_leetcode_player_submissions("alex")

    assert hidden == {"submissions": [], "hidden": True}


def test_record_match_submissions_scores_a_new_accept_once(db):
    room, player, start, end, room_problems = open_match(db)
    inside = start + timedelta(minutes=1)
    outside = start - timedelta(minutes=10)
    rows = record_match_submissions(
        db,
        room,
        player,
        [
            submission("other", inside, "Accepted"),
            {"titleSlug": "two-sum", "timestamp": "nope", "statusDisplay": "Accepted"},
            submission("two-sum", outside, "Accepted"),
            submission("two-sum", inside, "Wrong Answer"),
            submission("two-sum", inside + timedelta(seconds=30), "Accepted"),
        ],
        room_problems,
        start,
        end,
    )
    db.add_all(rows)
    db.flush()

    assert player.score == 1
    assert len(rows) == 1
    assert rows[0].current_status == "Accepted"

    again = record_match_submissions(
        db,
        room,
        player,
        [submission("two-sum", inside, "Accepted")],
        room_problems,
        start,
        end,
    )
    assert again == []
    assert player.score == 1


def test_record_match_submissions_upgrades_a_wrong_answer(db):
    room, player, start, end, room_problems = open_match(db)
    inside = start + timedelta(minutes=1)
    wrong = record_match_submissions(
        db,
        room,
        player,
        [submission("two-sum", inside, "Wrong Answer")],
        room_problems,
        start,
        end,
    )
    db.add_all(wrong)
    db.flush()
    assert player.score == 0

    upgraded = record_match_submissions(
        db,
        room,
        player,
        [submission("two-sum", inside + timedelta(seconds=20), "Accepted")],
        room_problems,
        start,
        end,
    )
    assert upgraded == []
    assert player.score == 1
    stored = db.query(Submission).one()
    assert stored.current_status == "Accepted"


def test_record_match_submissions_ignores_problems_outside_the_room(db):
    room, player, start, end, room_problems = open_match(db)
    rows = record_match_submissions(
        db,
        room,
        player,
        [submission("not-in-this-room", start + timedelta(minutes=1), "Accepted")],
        room_problems,
        start,
        end,
    )
    assert rows == []
    assert player.score == 0


def test_leetcode_graphql_success_and_failures():
    class Response:
        def __init__(self, payload, fail=False):
            self.payload = payload
            self.fail = fail

        def raise_for_status(self):
            if self.fail:
                raise RuntimeError("http down")

        def json(self):
            return self.payload

    with patch("app.domain.matches.leetcode.requests.post", return_value=Response({"data": {}})):
        assert leetcode_graphql("query {}") == {"data": {}}

    with patch("app.domain.matches.leetcode.requests.post", return_value=Response({}, fail=True)):
        with pytest.raises(RuntimeError, match="LeetCode API error"):
            leetcode_graphql("query {}")

    with patch(
        "app.domain.matches.leetcode.requests.post",
        return_value=Response({"errors": [{"message": "bad query"}]}),
    ):
        with pytest.raises(RuntimeError, match="bad query"):
            leetcode_graphql("query {}")


def test_lookup_leetcode_user():
    with patch(
        "app.domain.matches.leetcode.leetcode_graphql",
        return_value={"data": {"matchedUser": {"username": "Alex"}}},
    ):
        assert lookup_leetcode_user("alex") == "Alex"

    with patch(
        "app.domain.matches.leetcode.leetcode_graphql",
        return_value={"data": {"matchedUser": None}},
    ):
        with pytest.raises(ValueError, match="not found"):
            lookup_leetcode_user("missing")
