from datetime import datetime, timezone

from app.common import to_db_time
from app.models import Player, Room, RoomPlayer, RoomProblem

# What catalog's GET /problems returns for problem 1 (the catalog owns the details).
TWO_SUM = {
    "id": 1,
    "title": "Two Sum",
    "slug": "two-sum",
    "url": "https://leetcode.com/problems/two-sum/",
    "difficulty": "Easy",
}


def add_player(db, username):
    player = Player(lc_user=username)
    db.add(player)
    db.flush()
    return player


def add_room(db, host, code="ROOM01", status="Created", minutes=30, created=None, start=None, end=None):
    room = Room(
        room_code=code,
        host_id=host.id,
        current_status=status,
        duration_min=minutes,
        creation_time=to_db_time(created or datetime.now(timezone.utc)),
        start_time=to_db_time(start) if start else None,
        end_time=to_db_time(end) if end else None,
    )
    db.add(room)
    db.flush()
    return room


def seat(db, room, player, score=0, result="Created"):
    link = RoomPlayer(
        room_id=room.id,
        player_id=player.id,
        joined_at=to_db_time(datetime.now(timezone.utc)),
        score=score,
        result=result,
    )
    db.add(link)
    db.flush()
    return link


def attach(db, room, problem_id=1, order=0):
    """Deal a catalog problem (by ID only: no FK across the seam) into a room."""

    link = RoomProblem(room_id=room.id, problem_id=problem_id, display_order=order)
    db.add(link)
    db.flush()
    return link
