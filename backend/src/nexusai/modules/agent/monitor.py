"""Watches every agent all the time, whether or not anyone has the page open.

Tokens come from the gateway's record of every model call and messages from the router's record of
every message, so no agent can avoid being counted. Each alert is raised once and kept, so the
person sees it on Today and on the Agents page even if it happened overnight.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from nexusai.contracts.agent import MonitorAlert
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import cards, channel

MIGRATION = Migration(
    "agent_monitor_001",
    """
CREATE TABLE monitor_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, agent TEXT, task INTEGER,
  detail TEXT NOT NULL, key TEXT NOT NULL UNIQUE, time TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE INDEX monitor_alerts_time ON monitor_alerts (seen, id);
""",
)
# Where each kind of alert takes the person.
# About usage, not something to act on now, so they only notify when the person asks for them.
TOKEN_ALERTS = frozenset({"spike", "cap"})
# For whoever tunes the agents: kept on the Agents page, never a notification.
QUIET_ALERTS = frozenset({"detour"})
# A question about the day, which "Your day" already answers. Only for this check, never to route.
DAY_QUESTION = re.compile(
    r"\b(today|my day|this morning|needs? me|on my plate|overdue|catch me up"
    r"|what'?s (?:pending|open|due|left))\b",
    re.IGNORECASE,
)
MAIL_SEARCHES = frozenset({"search_mail", "semantic_search"})
LINKS = {
    "spike": "/agent/channel?tab=team",
    "silence": "/agent/channel?tab=tasks",
    "cap": "/agent/channel?tab=team",
}


def _now() -> datetime:
    return datetime.now(UTC)


def raise_alert(
    ctx: Context,
    kind: str,
    key: str,
    detail: str,
    agent: str | None = None,
    task: int | None = None,
) -> bool:
    """Saves the alert and tells the person, once per key. False when it was already raised."""
    tell = kind not in QUIET_ALERTS and (
        kind not in TOKEN_ALERTS or channel.load_quiet(ctx.bus.db).token_alerts
    )
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT OR IGNORE INTO monitor_alerts (kind, agent, task, detail, key, time)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, agent, task, detail, key, _now().isoformat()),
        )
        if not cursor.rowcount:
            return False
        if tell:
            channel.notify(ctx, work, detail, "", LINKS.get(kind, "/agent/channel"), "agent", False)
        work.emit("monitor.alerted", {"kind": kind}, source="agent", trace_id=ctx.trace_id)
    return True


def tokens_since(db: Database, agent: str, since: datetime, until: datetime | None = None) -> int:
    rows = db.fetch_all(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS n FROM model_calls"
        " WHERE agent = ? AND time >= ? AND time < ?",
        (agent, since.isoformat(), (until or _now() + timedelta(seconds=1)).isoformat()),
    )
    return int(rows[0]["n"])


def usual_hour(db: Database, agent: str) -> float:
    """An agent's average hour over the last 7 days, before this hour."""
    now = _now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    return tokens_since(db, agent, hour - timedelta(days=7), hour) / (7 * 24)


def check(ctx: Context, runtime: Any) -> None:
    """Runs from the trigger loop, at least once a minute."""
    _spikes(ctx)
    _silence(ctx, runtime)
    _detours(ctx)


def _spikes(ctx: Context) -> None:
    """Slow leaks stay under every cap, so each hour is compared with the agent's usual hour."""
    db = ctx.bus.db
    settings = ctx.config.team
    now = _now()
    hour = now.replace(minute=0, second=0, microsecond=0)
    for agent in cards.all_cards(db, include_hidden=True):
        used = tokens_since(db, agent, hour)
        usual = usual_hour(db, agent)
        if used < settings.spike_min_tokens or used < usual * settings.spike_factor:
            continue
        name = cards.name(db, agent)
        times = f"{used / usual:.0f} times its usual hour" if usual else "far more than usual"
        raise_alert(
            ctx,
            "spike",
            f"spike:{agent}:{hour.isoformat()}",
            f"{name} used {used:,} tokens this hour, {times}. Check what it's doing.",
            agent=agent,
        )


def _detours(ctx: Context) -> None:
    """A chat about the day that searched mail before anything else. The prompt says to start
    from "Your day", so a model that slips from it shows up here, once for each run."""
    db = ctx.bus.db
    since = (_now() - timedelta(hours=1)).isoformat()
    for turn in db.fetch_all(
        "SELECT t.id, t.session, t.text, t.created, COALESCE(t.agent, s.agent) AS agent"
        " FROM agent_turns t JOIN agent_sessions s ON s.id = t.session"
        " WHERE t.closed = 1 AND t.origin = 'person' AND t.created > ?",
        (since,),
    ):
        if cards.engine(db, turn["agent"]) != "session" or not DAY_QUESTION.search(turn["text"]):
            continue
        # Its own steps: up to the next run in the same chat.
        following = db.fetch_all(
            "SELECT created FROM agent_turns WHERE session = ? AND id > ? ORDER BY id LIMIT 1",
            (turn["session"], turn["id"]),
        )
        first = db.fetch_all(
            "SELECT tool FROM tool_calls WHERE session = ? AND started >= ? AND started < ?"
            " ORDER BY id LIMIT 1",
            (turn["session"], turn["created"], following[0]["created"] if following else "9999"),
        )
        if first and first[0]["tool"] in MAIL_SEARCHES:
            asked = " ".join(turn["text"].split())[:80]
            raise_alert(
                ctx,
                "detour",
                f"detour:{turn['id']}",
                f'{cards.name(db, turn["agent"])} searched mail first for "{asked}", instead of'
                " starting from Your day.",
                agent=turn["agent"],
            )


def _silence(ctx: Context, runtime: Any) -> None:
    """A task whose run has made no new step for too long is hung, so it's stopped and blocked."""
    from nexusai.modules.agent import team

    db = ctx.bus.db
    limit = (_now() - timedelta(minutes=ctx.config.team.silence_minutes)).isoformat()
    for row in db.fetch_all(
        "SELECT * FROM team_tasks WHERE state = 'working' AND owner_session IS NOT NULL"
    ):
        session = row["owner_session"]
        if runtime.active_turn(session) is None:
            continue
        # Waiting on the person, for an approval or an answer, isn't hung: they may take a while.
        if db.fetch_all(
            "SELECT 1 FROM agent_sessions WHERE id = ? AND status = 'waiting'", (session,)
        ):
            continue
        last = db.fetch_all(
            "SELECT MAX(t) AS last FROM (SELECT MAX(time) AS t FROM model_calls WHERE session = ?"
            " UNION ALL SELECT MAX(started) FROM tool_calls WHERE session = ?"
            " UNION ALL SELECT created FROM agent_turns WHERE id = ?)",
            (session, session, row["owner_turn"]),
        )[0]["last"]
        if not last or last > limit:
            continue
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE team_tasks SET state = 'blocked', failure = 'silence', wake = ?, updated = ?"
                " WHERE id = ? AND state = 'working'",
                (team.ASSIGNER, _now().isoformat(), row["id"]),
            )
            work.emit("team.changed", {"task": row["id"]}, source="agent", trace_id=ctx.trace_id)
        runtime.stop(session)
        raise_alert(
            ctx,
            "silence",
            f"silence:{row['id']}:{row['owner_turn']}",
            f"Task {row['id']} for {cards.name(db, row['owner'])} made no progress for "
            f"{ctx.config.team.silence_minutes} minutes, so it was stopped. Retry or cancel it.",
            agent=row["owner"],
            task=row["id"],
        )


def over_daily_cap(ctx: Context, agent: str, origin: str) -> str | None:
    """Background work for an agent stops at its daily cap. The person's own messages still go."""
    cap = ctx.config.team.agent_tokens_per_day
    if not cap or origin == cards.PERSON:
        return None
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = tokens_since(ctx.bus.db, agent, today)
    if used < cap:
        return None
    name = cards.name(ctx.bus.db, agent)
    raise_alert(
        ctx,
        "cap",
        f"cap:{agent}:{today.date().isoformat()}",
        f"{name} reached its {cap:,} tokens for today, so its background work waits for tomorrow.",
        agent=agent,
    )
    return f"{name} has used its {cap:,} tokens for today. Background work waits until tomorrow."


def alerts(db: Database, limit: int = 50) -> list[MonitorAlert]:
    return [
        MonitorAlert(
            id=row["id"],
            kind=row["kind"],
            agent=row["agent"],
            task_id=row["task"],
            detail=row["detail"],
            time=row["time"],
            seen=bool(row["seen"]),
        )
        for row in db.fetch_all("SELECT * FROM monitor_alerts ORDER BY id DESC LIMIT ?", (limit,))
    ]
