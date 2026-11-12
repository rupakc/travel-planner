"""For-you ranking, computed in SQLite (no model call).

``score = 2 * recency + engagement + taste`` where recency halves every ~2
days, engagement is ``(likes + 2 * saves)`` squashed into 0..1, and taste is
0.5 per idea tag the caller's interests share (capped at 1.0).
"""

MAX_INTERESTS = 10


def interest_tokens(interests: list | None) -> list[str]:
    """Lower-case, de-duplicated interest tags (the same form stored on ideas)."""
    out: list[str] = []
    for raw in interests or []:
        t = " ".join(str(raw).lower().split())[:30]
        if t and t not in out:
            out.append(t)
    return out[:MAX_INTERESTS]


def score_sql(interests: list[str]) -> tuple[str, dict]:
    """The ORDER BY expression and its named parameters."""
    params: dict = {}
    matches = []
    for n, t in enumerate(interest_tokens(interests)):
        params[f"tag{n}"] = '"' + t.replace('"', "") + '"'
        matches.append(f"(instr(i.tags_json, :tag{n}) > 0)")
    taste = f"MIN(1.0, 0.5 * ({' + '.join(matches)}))" if matches else "0.0"
    recency = (
        "(1.0 / (1.0 + MAX(0.0, julianday('now') - julianday(i.created_at)) / 2.0))"
    )
    eng = (
        "((SELECT COUNT(*) FROM idea_likes l WHERE l.idea_id = i.id)"
        " + 2.0 * (SELECT COUNT(*) FROM idea_saves s WHERE s.idea_id = i.id))"
    )
    return f"(2.0 * {recency} + ({eng} / ({eng} + 5.0)) + {taste})", params
