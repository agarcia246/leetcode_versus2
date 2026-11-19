"""Catalog domain: LeetCode topics and problems.

The catalog owns `problems`, `topics` and `problem_topics`. It knows nothing about
rooms or players. The matches domain reaches it only through `pick_problems` and
`get_problems`, which return plain dicts (the future HTTP response bodies).
"""

import random

import requests
from sqlalchemy.orm import Session

from app.domain.catalog.models import Problem, ProblemTopic, Topic
from app.domain.common import DIFFICULTIES

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


def problem_to_dict(problem: Problem) -> dict:
    """The shape the catalog hands to other domains (and later sends over HTTP)."""

    return {
        "id": problem.id,
        "title": problem.title,
        "slug": problem.lc_id,
        "url": problem.lc_url,
        "difficulty": problem.difficulty,
    }


def pick_problems(db: Session, count: int, topics: list[str], difficulty: str) -> list[dict]:
    """Fetch a filtered LeetCode set, store it, and return a random sample of `count`.

    Falls back to problems already stored when LeetCode is unreachable. Raises
    ValueError for an unknown topic or when fewer than `count` problems exist.
    """

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
        db.rollback()
        raise ValueError("Not enough problems available for selection")

    db.commit()
    return get_problems(db, problem_ids)


def get_problems(db: Session, problem_ids: list[int]) -> list[dict]:
    """Return the requested problems in the order of `problem_ids`. Unknown IDs are skipped."""

    if not problem_ids:
        return []

    rows = db.query(Problem).filter(Problem.id.in_(problem_ids)).all()
    by_id = {problem.id: problem for problem in rows}

    return [problem_to_dict(by_id[problem_id]) for problem_id in problem_ids if problem_id in by_id]
