"""Catalog domain: LeetCode topics/problems and match scoring from public submissions."""

from datetime import datetime, timezone
import random

import requests
from sqlalchemy.orm import Session

from app.domain.catalog.models import Problem, ProblemTopic, Topic
from app.domain.common import DIFFICULTIES, to_db_time
from app.domain.matches.models import Room, RoomPlayer, RoomProblem, Submission

LEETCODE_URL = "https://leetcode.com/graphql"
LEETCODE_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "Origin": "https://leetcode.com",
    "User-Agent": "Mozilla/5.0",
}
DIFFICULTY_TO_API = {
    "Easy": "EASY",
    "Medium": "MEDIUM",
    "Hard": "HARD",
}
API_TO_DIFFICULTY = {api_name: name for name, api_name in DIFFICULTY_TO_API.items()}


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


def leetcode_graphql(query: str, variables: dict | None = None) -> dict:
    """POST one GraphQL query to LeetCode."""

    try:
        response = requests.post(
            LEETCODE_URL,
            json={"query": query, "variables": variables or {}},
            headers=LEETCODE_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"LeetCode API error: {exc}") from exc

    if "data" not in payload and payload.get("errors"):
        message = payload["errors"][0].get("message", "Invalid LeetCode response")
        raise RuntimeError(f"LeetCode API error: {message}")

    return payload


def lookup_leetcode_user(username: str) -> str:
    """Return LeetCode's canonical username, or raise if the account does not exist."""

    query = """
    query ($username: String!) {
        matchedUser(username: $username) {
            username
        }
    }
    """

    payload = leetcode_graphql(query, {"username": username})
    matched = (payload.get("data") or {}).get("matchedUser")

    if not matched or not matched.get("username"):
        raise ValueError(f"LeetCode user '{username}' was not found")

    return matched["username"]


def fetch_topic_tags() -> list[dict]:
    """Return LeetCode topic tags as name/slug pairs."""

    query = """
    query {
        questionTopicTags {
            edges {
                node {
                    name
                    slug
                }
            }
        }
    }
    """

    payload = leetcode_graphql(query)
    edges = ((payload.get("data") or {}).get("questionTopicTags") or {}).get("edges") or []
    tags = []

    for edge in edges:
        node = edge.get("node") or {}
        name = (node.get("name") or "").strip()
        slug = (node.get("slug") or "").strip()
        if name and slug:
            tags.append({"name": name, "slug": slug})

    if not tags:
        raise RuntimeError("LeetCode API error: no topic tags returned")

    return tags


def get_or_create_topic(db: Session, topic_name: str) -> Topic:
    topic = db.query(Topic).filter(Topic.topic_name == topic_name).first()
    if topic is not None:
        return topic

    topic = Topic(topic_name=topic_name)
    db.add(topic)
    db.flush()
    return topic


def resolve_topics(db: Session, requested: list[str]) -> list[dict]:
    """Match requested names or slugs to LeetCode tags and store those tags."""

    tags = fetch_topic_tags()
    by_key = {}
    for tag in tags:
        by_key[tag["name"].lower()] = tag
        by_key[tag["slug"].lower()] = tag

    resolved = []
    seen = set()

    for topic in requested:
        tag = by_key.get(topic.strip().lower())
        if tag is None:
            raise ValueError(f"Unknown topic '{topic}'")
        if tag["slug"] in seen:
            continue
        seen.add(tag["slug"])
        get_or_create_topic(db, tag["name"])
        resolved.append(tag)

    return resolved


def list_match_filters(db: Session) -> dict:
    """Store the current LeetCode topic list and return the filters a client can send."""

    tags = fetch_topic_tags()
    for tag in tags:
        get_or_create_topic(db, tag["name"])

    db.commit()

    return {
        "difficulties": list(DIFFICULTIES),
        "topics": tags,
    }


def fetch_problems_for_topics(difficulty: str, topic_slugs: list[str], needed: int) -> list[dict]:
    """Fetch free LeetCode problems for any of the requested topics."""

    query = """
    query problemsetQuestionListV2($limit: Int, $skip: Int, $filters: QuestionFilterInput) {
        problemsetQuestionListV2(limit: $limit, skip: $skip, filters: $filters) {
            questions {
                title
                titleSlug
                difficulty
                paidOnly
                topicTags { name slug }
            }
            hasMore
        }
    }
    """

    found = {}
    api_difficulty = DIFFICULTY_TO_API[difficulty]

    for topic_slug in topic_slugs:
        added_for_topic = 0
        skip = 0
        while added_for_topic < needed and skip < 200:
            payload = leetcode_graphql(
                query,
                {
                    "limit": 50,
                    "skip": skip,
                    "filters": {
                        "filterCombineType": "ALL",
                        "difficultyFilter": {
                            "difficulties": [api_difficulty],
                            "operator": "IS",
                        },
                        "topicFilter": {
                            "topicSlugs": [topic_slug],
                            "operator": "IS",
                        },
                    },
                },
            )
            page = (payload.get("data") or {}).get("problemsetQuestionListV2") or {}
            questions = page.get("questions") or []

            if not questions:
                break

            for question in questions:
                slug = question.get("titleSlug")
                question_difficulty = API_TO_DIFFICULTY.get(
                    (question.get("difficulty") or "").upper()
                )
                if (
                    not slug
                    or slug in found
                    or question.get("paidOnly")
                    or question_difficulty != difficulty
                ):
                    continue
                found[slug] = question
                added_for_topic += 1

            if added_for_topic >= needed or not page.get("hasMore"):
                break

            skip += 50

    return list(found.values())


def upsert_problem(db: Session, question: dict) -> Problem:
    """Insert a LeetCode problem and its topic links."""

    slug = question["titleSlug"]
    difficulty = API_TO_DIFFICULTY[(question.get("difficulty") or "").upper()]
    problem = db.query(Problem).filter(Problem.lc_id == slug).first()

    if problem is None:
        problem = Problem(
            title=question["title"],
            lc_id=slug,
            lc_url=f"https://leetcode.com/problems/{slug}/",
            difficulty=difficulty,
        )
        db.add(problem)
        db.flush()

    for tag in question.get("topicTags") or []:
        name = (tag.get("name") or "").strip()
        if not name:
            continue
        topic = get_or_create_topic(db, name)
        link = (
            db.query(ProblemTopic)
            .filter(
                ProblemTopic.problem_id == problem.id,
                ProblemTopic.topic_id == topic.id,
            )
            .first()
        )
        if link is None:
            db.add(ProblemTopic(problem_id=problem.id, topic_id=topic.id))

    db.flush()
    return problem


def local_problem_ids(db: Session, topic_names: list[str], difficulty: str, count: int) -> list[int]:
    problems = (
        db.query(Problem.id)
        .join(ProblemTopic, Problem.id == ProblemTopic.problem_id)
        .join(Topic, Topic.id == ProblemTopic.topic_id)
        .filter(
            Topic.topic_name.in_(topic_names),
            Problem.difficulty == difficulty,
        )
        .distinct()
        .all()
    )
    problem_ids = [problem[0] for problem in problems]
    if len(problem_ids) <= count:
        return problem_ids
    return random.sample(problem_ids, count)


def add_problems_to_room(
    db: Session,
    count: int,
    topics: list[str],
    difficulty: str,
    room_id: int,
) -> None:
    """Fetch a filtered LeetCode set, store it, and attach a random sample to the room."""

    resolved = resolve_topics(db, topics)
    topic_names = [tag["name"] for tag in resolved]
    topic_slugs = [tag["slug"] for tag in resolved]

    try:
        questions = fetch_problems_for_topics(difficulty, topic_slugs, count)
        problem_ids = [upsert_problem(db, question).id for question in questions]
        if len(problem_ids) > count:
            problem_ids = random.sample(problem_ids, count)
    except RuntimeError:
        problem_ids = local_problem_ids(db, topic_names, difficulty, count)

    if len(problem_ids) < count:
        raise ValueError("Not enough problems available for selection")

    room_problems = []

    for index, problem_id in enumerate(problem_ids):
        room_problems.append(
            RoomProblem(
                room_id=room_id,
                problem_id=problem_id,
                display_order=index,
            )
        )

    db.add_all(room_problems)


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


def get_leetcode_player_submissions(lc_username: str) -> dict:
    """Fetch recent submissions of every status, plus the separate accepted list.

    LeetCode only returns about 20 rows from each public list. Accepted solves are
    read from both, so later wrong answers do not hide a solve. A null list means
    the profile did not share submissions.
    """

    query = """
    query recentSubmissions($username: String!, $limit: Int!) {
        recentSubmissionList(username: $username) {
            title
            titleSlug
            timestamp
            statusDisplay
            lang
        }
        recentAcSubmissionList(username: $username, limit: $limit) {
            title
            titleSlug
            timestamp
            statusDisplay
            lang
        }
    }
    """

    payload = leetcode_graphql(
        query,
        {"username": lc_username, "limit": 20},
    )
    data = payload.get("data") or {}
    recent = data.get("recentSubmissionList")
    accepted = data.get("recentAcSubmissionList")

    if recent is None and accepted is None:
        return {"submissions": [], "hidden": True}

    merged = []
    seen = set()

    for submission in (recent or []) + (accepted or []):
        slug = submission.get("titleSlug")
        timestamp = submission.get("timestamp")
        status = submission.get("statusDisplay")
        if not slug or timestamp is None:
            continue
        key = (slug, str(timestamp), status)
        if key in seen:
            continue
        seen.add(key)
        merged.append(submission)

    return {"submissions": merged, "hidden": False}


def record_match_submissions(
    db: Session,
    room: Room,
    room_player: RoomPlayer,
    submissions: list[dict],
    room_problem_slugs: set[str],
    start_time: datetime | None,
    end_time: datetime | None,
) -> list[Submission]:
    """Store one in-window result per problem. Only a new Accepted solve increases score."""

    grouped = {}

    for submission in submissions:
        slug = submission.get("titleSlug")
        if not slug or slug not in room_problem_slugs:
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
            .join(Problem, Problem.id == Submission.problem_id)
            .filter(
                Submission.room_id == room.id,
                Submission.player_id == room_player.player_id,
                Problem.lc_id == slug,
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

        problem_id = db.query(Problem.id).filter(Problem.lc_id == slug).scalar()
        if problem_id is None:
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
