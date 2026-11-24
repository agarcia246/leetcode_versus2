"""Matches domain calls to LeetCode: verifying players and reading their submissions.

Players and submissions belong to matches, so matches asks LeetCode about them
directly instead of going through the catalog. The catalog has its own client
for topics and problems. The small GraphQL helper is duplicated on purpose: once
the domains are separate services they cannot share a module.
"""

import requests

LEETCODE_URL = "https://leetcode.com/graphql"
LEETCODE_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "Origin": "https://leetcode.com",
    "User-Agent": "Mozilla/5.0",
}


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
