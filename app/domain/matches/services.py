"""Matches domain: rooms, players, lobby lifecycle, and results."""

from datetime import timedelta
import random
import string

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.catalog.models import Problem
from app.domain.catalog.services import (
    add_problems_to_room,
    get_leetcode_player_submissions,
    lookup_leetcode_user,
    record_match_submissions,
)
from app.domain.common import DIFFICULTIES, parse_db_time, to_db_time, utc_now
from app.domain.matches.models import (
    CreateRoomModel,
    GetRoomModel,
    JoinRoomModel,
    Player,
    Room,
    RoomPlayer,
    RoomProblem,
    StartRoomModel,
)

ROOM_STATUS_CREATED = "Created"
ROOM_STATUS_ACTIVE = "Active"
ROOM_STATUS_INACTIVE = "Inactive"
ROOM_STATUS_FINISHED = "Finished"

RESULT_IN_PROGRESS = "In_Progress"
RESULT_WINNER = "Winner"
RESULT_LOSER = "Loser"
FINAL_RESULTS = {RESULT_WINNER, RESULT_LOSER}


def assign_match_results(room_players: list[RoomPlayer]) -> None:
    """Highest score wins. A tie at the top shares the win. Zero solves is a loss."""

    if not room_players:
        return

    top_score = max(player.score for player in room_players)

    for player in room_players:
        if top_score > 0 and player.score == top_score:
            player.result = RESULT_WINNER
        else:
            player.result = RESULT_LOSER


def generate_room_code(db: Session) -> str:
    """Generate a unique 6-character room code."""

    letters = string.ascii_uppercase

    while True:
        room_code = "".join(random.choice(letters) for _ in range(6))

        exists = (
            db.query(Room.id)
            .filter(Room.room_code == room_code)
            .first()
        )

        if exists is None:
            return room_code


def get_or_create_player(db: Session, username: str) -> Player:
    """Fetch a verified LeetCode player, or create them."""

    cleaned = username.strip()
    player = (
        db.query(Player)
        .filter(func.lower(Player.lc_user) == cleaned.lower())
        .first()
    )

    if player is not None:
        return player

    leetcode_name = lookup_leetcode_user(cleaned)
    new_player = Player(lc_user=leetcode_name)
    db.add(new_player)
    db.flush()

    return new_player


def expire_inactive_lobby(room: Room, now=None) -> None:
    """A room that is never started becomes Inactive after its duration elapses."""

    if room.current_status != ROOM_STATUS_CREATED:
        return

    created = parse_db_time(room.creation_time)
    if created is None:
        return

    current = now or utc_now()
    if current >= created + timedelta(minutes=room.duration_min):
        room.current_status = ROOM_STATUS_INACTIVE


def add_player_to_room(db: Session, player_id: int, room_id: int) -> RoomPlayer | None:
    """Add a player to a room if not already present."""

    existing = (
        db.query(RoomPlayer)
        .filter(
            RoomPlayer.room_id == room_id,
            RoomPlayer.player_id == player_id,
        )
        .first()
    )

    if existing is not None:
        return None

    room_player = RoomPlayer(
        room_id=room_id,
        player_id=player_id,
        joined_at=to_db_time(utc_now()),
        score=0,
    )

    db.add(room_player)
    return room_player


def validate_room_settings(model: CreateRoomModel) -> None:
    """Reject a room that asks for a duration, size, or difficulty the match cannot run."""

    if model.duration < 1 or model.duration > 180:
        raise ValueError("duration must be between 1 and 180 minutes")

    if model.problem_count < 1 or model.problem_count > 10:
        raise ValueError("problem_count must be between 1 and 10")

    if model.difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be Easy, Medium, or Hard")

    if not model.topics:
        raise ValueError("at least one topic is required")


def create_room(db: Session, model: CreateRoomModel):
    """Create a room with problems and host."""

    try:
        validate_room_settings(model)
        code = generate_room_code(db)

        host = get_or_create_player(db, model.host_username)

        room = Room(
            room_code=code,
            host_id=host.id,
            current_status=ROOM_STATUS_CREATED,
            duration_min=model.duration,
            creation_time=to_db_time(utc_now()),
            start_time=None,
            end_time=None,
            last_polled_at=None,
            poll_error=None,
        )

        db.add(room)
        db.flush()

        add_problems_to_room(
            db=db,
            count=model.problem_count,
            topics=model.topics,
            difficulty=model.difficulty,
            room_id=room.id,
        )

        add_player_to_room(
            db=db,
            player_id=host.id,
            room_id=room.id,
        )

        db.commit()

        return {
            "room_code": room.room_code,
            "room_id": room.id,
            "host_id": host.id,
        }

    except Exception:
        db.rollback()
        raise


def join_room(db: Session, model: JoinRoomModel):
    """Join an existing room."""

    try:
        room = (
            db.query(Room)
            .filter(Room.room_code == model.room_code.upper())
            .first()
        )

        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")

        expire_inactive_lobby(room)
        if room.current_status == ROOM_STATUS_INACTIVE:
            db.commit()
            raise HTTPException(status_code=400, detail="Room is inactive")

        if room.current_status == ROOM_STATUS_FINISHED:
            raise HTTPException(status_code=400, detail="Room already finished")

        player = get_or_create_player(db, model.username)

        existing = (
            db.query(RoomPlayer)
            .filter(
                RoomPlayer.room_id == room.id,
                RoomPlayer.player_id == player.id,
            )
            .first()
        )

        if existing is not None:
            db.commit()
            return {
                "message": "Joined room",
                "room_code": room.room_code,
                "player_id": player.id,
            }

        room_player = add_player_to_room(
            db,
            player_id=player.id,
            room_id=room.id,
        )

        if room.current_status == ROOM_STATUS_ACTIVE and room_player is not None:
            room_player.result = RESULT_IN_PROGRESS

        db.commit()

        return {
            "message": "Joined room",
            "room_code": room.room_code,
            "player_id": player.id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def start_room(db: Session, model: StartRoomModel):
    """Start a room if host is valid."""

    try:
        room = (
            db.query(Room)
            .filter(Room.room_code == model.room_code.upper())
            .first()
        )

        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")

        expire_inactive_lobby(room)
        if room.current_status == ROOM_STATUS_INACTIVE:
            db.commit()
            raise HTTPException(status_code=400, detail="Room is inactive")

        if room.host_id != model.player_id:
            raise HTTPException(status_code=400, detail="Host must start room")

        if room.current_status != ROOM_STATUS_CREATED:
            raise HTTPException(status_code=400, detail="Room already started")

        room_players = (
            db.query(RoomPlayer)
            .filter(RoomPlayer.room_id == room.id)
            .all()
        )

        room_problems = (
            db.query(RoomProblem)
            .filter(RoomProblem.room_id == room.id)
            .all()
        )

        if len(room_players) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 players")

        if len(room_problems) < 1:
            raise HTTPException(status_code=400, detail="No problems in room")

        start_time = utc_now()

        room.start_time = to_db_time(start_time)
        room.end_time = to_db_time(start_time + timedelta(minutes=room.duration_min))
        room.current_status = ROOM_STATUS_ACTIVE
        room.poll_error = None

        for room_player in room_players:
            room_player.result = RESULT_IN_PROGRESS

        db.commit()

        return {
            "message": "Room started",
            "room_code": room.room_code,
            "start_time": room.start_time,
            "end_time": room.end_time,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def get_room(db: Session, model: GetRoomModel):
    """Fetch room state and poll submissions that landed during the match."""

    room = None

    try:
        room_code = model.room_code.upper()

        room = (
            db.query(Room)
            .filter(Room.room_code == room_code)
            .first()
        )

        if room is None:
            raise HTTPException(status_code=404, detail="Room not found")

        now = utc_now()
        expire_inactive_lobby(room, now)
        start_time = parse_db_time(room.start_time)
        end_time = parse_db_time(room.end_time)
        time_up = end_time is not None and now >= end_time

        player_rows = (
            db.query(RoomPlayer, Player)
            .join(Player, Player.id == RoomPlayer.player_id)
            .filter(RoomPlayer.room_id == room.id)
            .all()
        )
        room_players = [room_player for room_player, _player in player_rows]

        results_pending = any(
            room_player.result not in FINAL_RESULTS
            for room_player in room_players
        )
        should_poll = room.current_status == ROOM_STATUS_ACTIVE or (
            room.current_status == ROOM_STATUS_FINISHED and results_pending
        )

        if should_poll:
            room_problem_slugs = {
                lc_id
                for (lc_id,) in db.query(Problem.lc_id)
                .join(RoomProblem, Problem.id == RoomProblem.problem_id)
                .filter(RoomProblem.room_id == room.id)
                .all()
            }

            submissions_to_add = []
            player_errors = []

            for room_player, player in player_rows:
                try:
                    player_submissions = get_leetcode_player_submissions(player.lc_user)
                except RuntimeError as exc:
                    player_errors.append(f"{player.lc_user}: {exc}")
                    continue

                if player_submissions["hidden"]:
                    player_errors.append(
                        f"{player.lc_user}: LeetCode returned no submissions. The profile may be private."
                    )
                    continue

                submissions_to_add.extend(
                    record_match_submissions(
                        db,
                        room,
                        room_player,
                        player_submissions["submissions"],
                        room_problem_slugs,
                        start_time,
                        end_time,
                    )
                )

            if submissions_to_add:
                db.add_all(submissions_to_add)

            room.last_polled_at = to_db_time(now)
            room.poll_error = "; ".join(player_errors) if player_errors else None

        if time_up or room.current_status == ROOM_STATUS_FINISHED:
            room.current_status = ROOM_STATUS_FINISHED
            assign_match_results(room_players)

        problems = (
            db.query(Problem, RoomProblem.display_order)
            .join(RoomProblem, Problem.id == RoomProblem.problem_id)
            .filter(RoomProblem.room_id == room.id)
            .order_by(RoomProblem.display_order)
            .all()
        )

        db.commit()

        return {
            "room_code": room.room_code,
            "status": room.current_status,
            "start_time": room.start_time,
            "end_time": room.end_time,
            "players": [
                {
                    "player_id": room_player.player_id,
                    "username": player.lc_user,
                    "score": room_player.score,
                    "result": room_player.result,
                }
                for room_player, player in player_rows
            ],
            "problems": [
                {
                    "title": problem.title,
                    "slug": problem.lc_id,
                    "url": problem.lc_url,
                    "difficulty": problem.difficulty,
                    "display_order": display_order,
                }
                for problem, display_order in problems
            ],
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()

        if room is not None:
            room.poll_error = str(exc)
            db.commit()

        raise
