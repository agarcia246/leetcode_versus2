"""The only way the matches domain reaches the catalog domain.

Today both domains run in one process, so these functions call the catalog's
service functions directly, each with its own database session (as if the
catalog owned a separate database). When the domains become two services, each
body becomes an HTTP request to CATALOG_URL with a timeout. The signatures, the
returned dicts and the raised errors stay the same, so matches does not change:

    pick_problems -> POST {CATALOG_URL}/problems/pick
    get_problems  -> GET  {CATALOG_URL}/problems?ids=1,2,3

Errors the caller must handle:
    ValueError    the request was invalid (unknown topic, not enough problems)
    RuntimeError  the catalog could not answer (LeetCode down, later: catalog down)
"""

from app.database import SessionLocal
from app.domain.catalog import services as catalog


def pick_problems(count: int, topics: list[str], difficulty: str) -> list[dict]:
    """Return `count` problems matching the topics and difficulty.

    Each item: {"id", "title", "slug", "url", "difficulty"}.
    """

    db = SessionLocal()
    try:
        return catalog.pick_problems(db, count=count, topics=topics, difficulty=difficulty)
    finally:
        db.close()


def get_problems(problem_ids: list[int]) -> list[dict]:
    """Return the problems with these IDs, in the same order. Unknown IDs are left out."""

    if not problem_ids:
        return []

    db = SessionLocal()
    try:
        return catalog.get_problems(db, problem_ids)
    finally:
        db.close()
