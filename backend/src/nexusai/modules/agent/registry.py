"""Every agent there is, what starts it, and when it runs next, so none of them run unseen."""

from typing import Any

from nexusai.contracts.agent import AgentEntry
from nexusai.kernel.module import Context
from nexusai.modules.agent import mail_agent

INTERVIEW_AGENT = "interview"
WEEKDAYS = ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")
WHAT_THEY_DO = {
    "mail-brief": "Writes your morning brief from what needs you, and learns from your reactions.",
    "mail-review": "Looks for whole groups of mail to file, and only suggests.",
    "daily-prep": "Prepares your morning from the work board.",
    "prompt": "Runs the instructions you gave it.",
}
EVENT_WORDS = {
    "mail.received": "When any new mail arrives",
    "mail.urgent": "When important mail arrives",
}


def _when(row: Any) -> str:
    every = row["every"]
    if every == "hour":
        return "Every hour"
    if every == "day":
        return f"Every day at {row['time']}"
    if every == "week":
        return f"{WEEKDAYS[int(row['weekday'] or 0)]} at {row['time']}"
    return f"Once, on {row['date']} at {row['time']}"


def _session_facts(ctx: Context, session: str | None) -> tuple[str | None, int]:
    if not session:
        return None, 0
    rows = ctx.bus.db.fetch_all(
        "SELECT updated, input_tokens + output_tokens AS tokens FROM agent_sessions WHERE id = ?",
        (session,),
    )
    return (rows[0]["updated"], rows[0]["tokens"]) if rows else (None, 0)


def _mail_entry(ctx: Context, schedules: list[Any], is_running: Any) -> AgentEntry:
    session = mail_agent.SESSION_ID
    last, tokens = _session_facts(ctx, session)
    hourly = next((row for row in schedules if row["kind"] == "mail-hourly"), None)
    live = ctx.bus.db.fetch_all("SELECT enabled FROM agent_triggers WHERE id = 'mail-received'")
    on_mail = bool(live and live[0]["enabled"])
    on_timer = bool(hourly and hourly["enabled"])
    if on_mail and on_timer:
        when = "When new mail needs judging, and a check every hour"
    elif on_mail:
        when = "When new mail needs judging"
    elif on_timer:
        when = "A check every hour"
    else:
        when = "Only when you ask"
    enabled = mail_agent.enabled(ctx) and (on_mail or on_timer)
    return AgentEntry(
        id="mail-agent",
        name="Mail agent",
        does="Judges your mail: what matters, what needs a reply, what to chase and where it goes.",
        state="running" if is_running(session) else "active" if enabled else "off",
        when=when,
        next_run=hourly["next_run"] if hourly and on_timer else None,
        next_condition="Or as soon as new mail needs it" if on_mail else None,
        last_run=last,
        session=session,
        tokens=tokens,
    )


def _schedule_entry(ctx: Context, row: Any, is_running: Any) -> AgentEntry:
    last, tokens = _session_facts(ctx, row["last_session"])
    once_done = row["every"] == "once" and not row["next_run"]
    state = (
        "running"
        if row["last_session"] and is_running(row["last_session"])
        else "finished"
        if once_done
        else "active"
        if row["enabled"]
        else "off"
    )
    return AgentEntry(
        id=f"schedule-{row['id']}",
        name=row["title"],
        does=WHAT_THEY_DO.get(row["kind"], WHAT_THEY_DO["prompt"]),
        state=state,
        when=_when(row),
        next_run=row["next_run"] if state == "active" else None,
        last_run=row["last_run"] or last,
        session=row["last_session"],
        tokens=tokens,
    )


def _knowing_you(ctx: Context, is_running: Any) -> AgentEntry:
    rows = ctx.bus.db.fetch_all(
        "SELECT id FROM agent_sessions WHERE agent = ? ORDER BY updated DESC LIMIT 1",
        (INTERVIEW_AGENT,),
    )
    session = rows[0]["id"] if rows else None
    last, tokens = _session_facts(ctx, session)
    state = "running" if session and is_running(session) else "finished" if session else "active"
    return AgentEntry(
        id="know-you-better",
        name="Know you better",
        does="Asks a few questions so the agents judge your mail the way you would.",
        state=state,
        when="Once, after it has read your past mail",
        next_condition="Waiting for the Mail agent to finish reading" if not session else None,
        last_run=last,
        session=session,
        tokens=tokens,
    )


def _reader(ctx: Context) -> AgentEntry:
    state = mail_agent.learning_state(ctx)
    done, total = mail_agent.learning_progress(ctx)
    return AgentEntry(
        id="mail-reader",
        name="Reading past mail",
        does="Reads your own conversations first, and notes what matters about you.",
        state="running" if state in {"reading", "wrapping"} else "finished" if state else "active",
        when="Once after mail syncs, and again when you ask it to read more",
        next_condition=f"{done} of {total} read" if state == "reading" else None,
        last_run=None,
        session=mail_agent.SESSION_ID if state else None,
    )


def _custom_triggers(ctx: Context, is_running: Any) -> list[AgentEntry]:
    entries = []
    for row in ctx.bus.db.fetch_all("SELECT * FROM agent_triggers WHERE kind != 'mail'"):
        last, tokens = _session_facts(ctx, row["session"])
        running = row["session"] and is_running(row["session"])
        entries.append(
            AgentEntry(
                id=f"trigger-{row['id']}",
                name=row["title"],
                does=WHAT_THEY_DO["prompt"],
                state="running" if running else "active" if row["enabled"] else "off",
                when=EVENT_WORDS.get(row["event"], f"When {row['event']} happens"),
                next_condition="The next time that happens" if row["enabled"] else None,
                last_run=last,
                session=row["session"],
                tokens=tokens,
            )
        )
    return entries


def _past(ctx: Context, known: set[str | None]) -> list[AgentEntry]:
    """Agents that ran and have since been removed, so what used to run stays on record."""
    rows = ctx.bus.db.fetch_all(
        "SELECT id, title, updated, input_tokens + output_tokens AS tokens FROM agent_sessions"
        " WHERE agent IN ('scheduled', 'daily-prep') AND archived = 0 ORDER BY updated DESC"
    )
    return [
        AgentEntry(
            id=f"past-{row['id']}",
            name=row["title"],
            does="No longer set up. Its last conversation is still here.",
            state="past",
            when="Doesn't run any more",
            last_run=row["updated"],
            session=row["id"],
            tokens=row["tokens"],
        )
        for row in rows
        if row["id"] not in known
    ]


def entries(ctx: Context, is_running: Any) -> list[AgentEntry]:
    schedules = ctx.bus.db.fetch_all("SELECT * FROM schedules ORDER BY id")
    shown = [
        _mail_entry(ctx, schedules, is_running),
        _reader(ctx),
        _knowing_you(ctx, is_running),
        *(
            _schedule_entry(ctx, row, is_running)
            for row in schedules
            if row["kind"] != "mail-hourly"
        ),
        *_custom_triggers(ctx, is_running),
    ]
    known = {row["last_session"] for row in schedules}
    order = {"running": 0, "active": 1, "finished": 2, "off": 3, "past": 4}
    return sorted([*shown, *_past(ctx, known)], key=lambda entry: order[entry.state])
