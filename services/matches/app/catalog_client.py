"""The only way the matches service reaches the catalog service: HTTP.

    pick_problems -> POST {CATALOG_URL}/problems/pick
    get_problems  -> GET  {CATALOG_URL}/problems?ids=1,2,3

Every call has a timeout (CATALOG_TIMEOUT_S). The returned dicts have the shape of
catalog's ProblemOut: {"id", "title", "slug", "url", "difficulty"}.

Errors the caller must handle:
    ValueError    the catalog refused the request (400: unknown topic, not enough problems)
    RuntimeError  the catalog could not answer (down, timed out, or LeetCode failed behind it)
"""

import requests

from app import config



class CatalogUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Catalog did not answer: down, timed out, or still starting (cold start).")

def _detail(response: requests.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text







def _call(method: str, path: str, **kwargs):
    url = config.CATALOG_URL.rstrip("/") + path
    try:
        response = requests.request(method, url, timeout=config.CATALOG_TIMEOUT_S, **kwargs)
    except requests.RequestException:
        raise CatalogUnavailable()

    if response.status_code == 400:
        raise ValueError(_detail(response))
    elif response.status_code == 502:
        raise RuntimeError(f"Catalog service error {response.status_code}: {_detail(response)}")
    if response.status_code != 200:
        raise CatalogUnavailable()

    return response.json()


def pick_problems(count: int, topics: list[str], difficulty: str) -> list[dict]:
    """Return `count` problems matching the topics and difficulty."""

    return _call(
        "POST",
        "/problems/pick",
        json={"count": count, "topics": topics, "difficulty": difficulty},
    )


def get_problems(problem_ids: list[int]) -> list[dict]:
    """Return the problems with these IDs, in the same order. Unknown IDs are left out."""

    if not problem_ids:
        return []

    return _call("GET", "/problems", params={"ids": ",".join(str(i) for i in problem_ids)})
