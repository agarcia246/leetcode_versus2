"""Matches domain: rooms, players, lobby lifecycle, and results."""

from datetime import datetime, timedelta, timezone
import random
import string

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.common import DIFFICULTIES, parse_db_time, to_db_time, utc_now
from app.domain.matches import catalog_client
from app.domain.matches.leetcode import get_leetcode_player_submissions, lookup_leetcode_user
from app.domain.matches.models import (
    CreateRoomModel,
    GetRoomModel,
    JoinRoomModel,
    Player,
    Room,
    RoomPlayer,
    RoomProblem,
    StartRoomModel,
    Submission,
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


def add_problems_to_room(db: Session, room_id: int, problems: list[dict]) -> None:
    """Deal the problems the catalog picked into the room, in order."""

    db.add_all(
        RoomProblem(
            room_id=room_id,
            problem_id=problem["id"],
            display_order=index,
        )
        for index, problem in enumerate(problems)
    )


def submission_in_window(
    submission_time: datetime,
    start_time: datetime | None,
    end_time: datetime | None,
) -> bool:
    """Count a solve only after the match starts and before it ends."""

    if start_time is None or submission_time < start_time:
        return False

    if end_time is not None and submission_time > end_time:
        return False

    return True


def canonical_submission_status(status_display: str | None) -> str:
    """Map a LeetCode status onto the statuses stored for a match."""

    normalized = (status_display or "").strip().lower()
    if normalized == "accepted":
        return "Accepted"
    if normalized == "wrong answer":
        return "Wrong_Answer"
    if normalized == "time limit exceeded":
        return "Time_Limit"
    return "Pending"


def record_match_submissions(
    db: Session,
    room: Room,
    room_player: RoomPlayer,
    submissions: list[dict],
    problem_ids_by_slug: dict[str, int],
    start_time: datetime | None,
    end_time: datetime | None,
) -> list[Submission]:
    """Store one in-window result per problem. Only a new Accepted solve increases score.

    `problem_ids_by_slug` maps the room's problem slugs to catalog problem IDs.
    Submissions for any other problem are ignored.
    """

    grouped = {}

    for submission in submissions:
        slug = submission.get("titleSlug")
        if not slug or slug not in problem_ids_by_slug:
            continue

        try:
            submission_time = datetime.fromtimestamp(
                int(submission["timestamp"]),
                tz=timezone.utc,
            )
        except (TypeError, ValueError, KeyError):
            continue

        if not submission_in_window(submission_time, start_time, end_time):
            continue

        grouped.setdefault(slug, []).append((submission_time, submission))

    submissions_to_add = []

    for slug, attempts in grouped.items():
        problem_id = problem_ids_by_slug[slug]
        accepted_attempts = [
            (submission_time, submission)
            for submission_time, submission in attempts
            if canonical_submission_status(submission.get("statusDisplay")) == "Accepted"
        ]

        if accepted_attempts:
            submission_time, _submission = min(accepted_attempts, key=lambda item: item[0])
            status = "Accepted"
        else:
            submission_time, submission = max(attempts, key=lambda item: item[0])
            status = canonical_submission_status(submission.get("statusDisplay"))

        existing_submission = (
            db.query(Submission)
            .filter(
                Submission.room_id == room.id,
                Submission.player_id == room_player.player_id,
                Submission.problem_id == problem_id,
            )
            .first()
        )

        if existing_submission is not None:
            if existing_submission.current_status == "Accepted":
                continue
            if status == "Accepted":
                existing_submission.current_status = "Accepted"
                existing_submission.submitted_at = to_db_time(submission_time)
                room_player.score += 1
            continue

        submissions_to_add.append(
            Submission(
                room_id=room.id,
                player_id=room_player.player_id,
                problem_id=problem_id,
                submitted_at=to_db_time(submission_time),
                current_status=status,
            )
        )

        if status == "Accepted":
            room_player.score += 1

    return submissions_to_add


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

        # Ask the catalog first, before this domain writes anything: if the catalog
        # cannot supply the problems, no half-built room or player is left behind.
        problems = catalog_client.pick_problems(
            count=model.problem_count,
            topics=model.topics,
            difficulty=model.difficulty,
        )
        if len(problems) < model.problem_count:
            raise ValueError("Not enough problems available for selection")

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
            room_id=room.id,
            problems=problems[: model.problem_count],
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

        # Was a join with the catalog's problems table. Now: read this room's
        # problem IDs here, and ask the catalog for their details in one call.
        room_problems = (
            db.query(RoomProblem)
            .filter(RoomProblem.room_id == room.id)
            .order_by(RoomProblem.display_order)
            .all()
        )
        catalog_problems = {
            problem["id"]: problem
            for problem in catalog_client.get_problems(
                [room_problem.problem_id for room_problem in room_problems]
            )
        }

        if should_poll:
            problem_ids_by_slug = {
                problem["slug"]: problem_id
                for problem_id, problem in catalog_problems.items()
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
                        problem_ids_by_slug,
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
                    "title": catalog_problems[room_problem.problem_id]["title"],
                    "slug": catalog_problems[room_problem.problem_id]["slug"],
                    "url": catalog_problems[room_problem.problem_id]["url"],
                    "difficulty": catalog_problems[room_problem.problem_id]["difficulty"],
                    "display_order": room_problem.display_order,
                }
                for room_problem in room_problems
                # No FK across the seam: a problem the catalog no longer has is skipped.
                if room_problem.problem_id in catalog_problems
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
