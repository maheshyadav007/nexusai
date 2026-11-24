"""Briefs reach Today only through the brief agent's update_brief, never from what it replies."""

import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent import citations
from nexusai.modules.agent.prompt_data import untrusted
from nexusai.modules.mail import accounts
from nexusai.modules.mail.store import hidden_from_ai

MIGRATION = Migration(
    "agent_brief_artifacts_001",
    """
CREATE TABLE brief_inputs(turn INTEGER PRIMARY KEY, account TEXT NOT NULL, snapshot TEXT NOT NULL);
CREATE TABLE brief_artifacts(
 id INTEGER PRIMARY KEY, turn INTEGER NOT NULL UNIQUE, session TEXT NOT NULL, account TEXT NOT NULL,
 text TEXT NOT NULL, created TEXT NOT NULL, partial INTEGER NOT NULL DEFAULT 0, snapshot TEXT NOT NULL);
CREATE TABLE brief_artifact_feedback(
 artifact INTEGER PRIMARY KEY, rating TEXT, comment TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL);
""",
)


# The brief keeps its citations, numbered, with the sources they point to.
SOURCES_MIGRATION = Migration(
    "agent_brief_sources_001",
    "ALTER TABLE brief_artifacts ADD COLUMN sources TEXT NOT NULL DEFAULT '[]';",
)
# The brief in its parts, so Today lays it out the same way every day. An older brief has none.
SECTIONS_MIGRATION = Migration(
    "agent_brief_sections_001",
    "ALTER TABLE brief_artifacts ADD COLUMN sections TEXT;",
)
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
REPLY_PREFIX = re.compile(r"^(?:(?:re|fwd?|aw|sv)\s*:\s*)+", re.IGNORECASE)
# Shorter subjects, like "Hi", would match bullets that aren't about them.
SUBJECT_MATCH_FROM = 8


def snapshot(ctx: Context) -> str:
    account = accounts.current_account(ctx.config)
    sections: list[str] = []
    truncated = False
    queries = (
        (
            "Open tasks (including proposals)",
            "SELECT t.id,t.title,t.due,t.status,t.proposed,t.thread FROM tasks t LEFT JOIN threads m ON m.id=t.thread WHERE t.status != 'done' AND (t.thread IS NULL OR m.account=?) ORDER BY t.due IS NULL,t.due,t.id",
        ),
        (
            "Reminders (including proposals)",
            "SELECT r.id,r.title,r.due_at,r.proposed,r.thread FROM reminders r LEFT JOIN threads m ON m.id=r.thread WHERE r.fired=0 AND (r.thread IS NULL OR m.account=?) ORDER BY r.due_at,r.id",
        ),
        (
            "Open shared obligations",
            "SELECT w.id,w.kind,w.title,w.due,w.thread FROM work_board w LEFT JOIN threads m ON m.id=w.thread WHERE w.done=0 AND (w.thread IS NULL OR m.account=?) ORDER BY w.due IS NULL,w.due,w.id",
        ),
        (
            "Unfinished mail, including archived conversations",
            # What a folder keeps from the AI stays out of the brief, whatever it was judged before.
            "SELECT id,subject,status,importance,next_action,follow_up_on,decision_version FROM threads WHERE account=? AND in_trash=0"
            f" AND NOT {hidden_from_ai()} AND status IN ('waiting_on_you','waiting_on_others') ORDER BY importance='high' DESC,last_date DESC",
        ),
    )
    for label, query in queries:
        rows = ctx.bus.db.fetch_all(query, (account,))
        truncated = truncated or len(rows) > 100
        # All obligations are represented in counts; bounded detail is explicit, never silent.
        detail = "\n".join(json.dumps(dict(row), ensure_ascii=False) for row in rows[:100])
        sections.append(
            f"{label}: {len(rows)} total; {min(len(rows), 100)} shown.\n{detail or 'None.'}"
        )
    learning = ctx.bus.db.fetch_all("SELECT value FROM agent_defaults WHERE key='mail_learning'")
    pending = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) n FROM trigger_runs WHERE trigger='mail-received' AND status IN ('pending','running')"
    )[0]["n"]
    from typing import cast

    from nexusai.contracts.mail import GetMailStatus, MailStatus
    from nexusai.modules.mail import module as mail

    sync = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    incomplete_sync = bool(sync.account and (sync.state != "live" or sync.backfill_remaining))
    coverage = json.dumps(
        {
            "partial": bool(pending or truncated or incomplete_sync),
            "sync": sync.state,
            "omitted_detail": truncated,
        }
    )
    return (
        f"Coverage: {coverage}\n"
        f"Snapshot at {datetime.now(UTC).isoformat()}; account {account}; {pending} mail events not yet judged. "
        "This snapshot may be incomplete while mail is syncing or being judged. Counts include omitted detail; use list_tasks/list_reminders/read_work_board when needed. "
        f"Historical learning state: {learning[0]['value'] if learning else 'not started or skipped'}.\n"
        + untrusted("\n\n".join(sections))
    )


def coverage(ctx: Context) -> str:
    """Whether the plate is complete, in a sentence: mail still coming in or being judged means
    the brief should say its picture is partial."""
    from typing import cast

    from nexusai.contracts.mail import GetMailStatus, MailStatus
    from nexusai.modules.mail import module as mail

    pending = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) n FROM trigger_runs WHERE trigger='mail-received' AND status IN ('pending','running')"
    )[0]["n"]
    sync = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    syncing = bool(sync.account and (sync.state != "live" or sync.backfill_remaining))
    if not pending and not syncing:
        return "Coverage: all mail is in and judged, so this is the whole picture."
    reasons = [
        f"{pending} emails are still being judged" if pending else "",
        "mail is still coming in" if syncing else "",
    ]
    # The app says this in a quiet line under the brief; in it, it would read as news.
    return (
        "Coverage: partial, because "
        + " and ".join(r for r in reasons if r)
        + ". The app notes this under the brief, so don't write it as a bullet."
    )


def _line(text: str) -> str:
    """One item, without the bullet a model may still put in front of it."""
    return BULLET.sub("", " ".join(text.split()))


def as_text(lead: str, new: list[str], still_open: list[str]) -> str:
    """The same brief as Markdown: for the next brief to read, and for the person's history."""
    parts = [lead]
    for heading, items in (("New", new), ("Still open", still_open)):
        if items:
            parts.append(f"**{heading}**\n" + "\n".join(f"- {item}" for item in items))
    return "\n\n".join(parts)


def save(ctx: Context, session: str, lead: str, new: list[str], still_open: list[str]) -> str:
    """The brief agent's update_brief. One brief per run: saving again in the same run replaces it."""
    turns = ctx.bus.db.fetch_all(
        "SELECT id FROM agent_turns WHERE session=? AND closed=0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if not turns:
        return "There's no run to save this brief from."
    turn = turns[0]["id"]
    lead = " ".join(lead.split())
    new = [line for line in map(_line, new) if line]
    still_open = [line for line in map(_line, still_open) if line]
    text = as_text(lead, new, still_open)
    missing = uncited(ctx, text)
    cited = citations.Citations(ctx, turn)
    # One numbering across the parts, so [2] is the same email wherever it's cited.
    sections = {
        "lead": cited.rewrite(lead),
        "new": [cited.rewrite(line) for line in new],
        "open": [cited.rewrite(line) for line in still_open],
    }
    shown = as_text(sections["lead"], sections["new"], sections["open"])
    part = cited.part()
    sources = part[0]["data"]["sources"] if part else []
    inputs = ctx.bus.db.fetch_all("SELECT * FROM brief_inputs WHERE turn=?", (turn,))
    account = inputs[0]["account"] if inputs else accounts.current_account(ctx.config)
    # Chat and team runs have no snapshot of their own, so take one now for coverage.
    data = inputs[0]["snapshot"] if inputs else snapshot(ctx)
    pending = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) n FROM trigger_runs WHERE trigger='mail-received' AND status IN ('pending','running')"
    )[0]["n"]
    coverage = {}
    if data.startswith("Coverage: "):
        with suppress(ValueError, IndexError):
            coverage = json.loads(data.splitlines()[0].removeprefix("Coverage: "))
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO brief_artifacts(turn,session,account,text,created,partial,snapshot,sources,sections)"
            " VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(turn) DO UPDATE SET text=excluded.text,"
            "created=excluded.created,partial=excluded.partial,sources=excluded.sources,"
            "sections=excluded.sections",
            (
                turn,
                session,
                account,
                shown,
                datetime.now(UTC).isoformat(),
                int(bool(pending or coverage.get("partial"))),
                data,
                json.dumps(sources),
                json.dumps(sections),
            ),
        )
        work.emit("brief.ready", {"turn": turn}, source="agent", trace_id=ctx.trace_id)
    saved = "Saved. It's at the top of their Today page now."
    if not missing:
        return saved
    # Saved anyway, so a brief is never lost to a missing marker. One more call fixes it.
    return (
        f"{saved}\n\nNote: these lines are about mail on the plate but have no marker. Add each "
        "marker straight after what it supports, then call update_brief again with the whole brief:\n"
        + "\n".join(missing)
    )


def done_since(ctx: Context, since: str) -> list[dict[str, str]]:
    """What got finished since `since`, worked out by the app, so the brief never has to say it:
    tasks ticked, reminders that went off and matters closed. Newest first."""
    db = ctx.bus.db
    found = [
        {"title": row["title"], "when": row["completed"], "why": row["looks_done"] or ""}
        for row in db.fetch_all(
            "SELECT title, completed, looks_done FROM tasks WHERE status = 'done'"
            " AND proposed = 0 AND completed >= ?",
            (since,),
        )
    ]
    now = datetime.now(UTC).isoformat()
    found += [
        {"title": row["title"], "when": row["due_at"], "why": "Reminder went off"}
        for row in db.fetch_all(
            "SELECT title, due_at FROM reminders WHERE fired = 1 AND proposed = 0"
            " AND due_at >= ? AND due_at <= ?",
            (since[:16], now[:16]),
        )
    ]
    found += [
        {"title": row["title"], "when": row["time"], "why": "Matter done"}
        for row in db.fetch_all(
            "SELECT m.title, e.time FROM matter_events e JOIN matters m ON m.id = e.matter"
            " WHERE e.kind = 'done' AND e.time >= ? AND m.account = ?",
            (since, accounts.current_account(ctx.config)),
        )
    ]
    return sorted(found, key=lambda item: item["when"] or "", reverse=True)


def uncited(ctx: Context, text: str) -> list[str]:
    """Bullets that name a thread on the plate by its subject and cite nothing, each with the
    marker it needs, so a small model only has to copy it."""
    from nexusai.modules.agent import mail_agent

    plate = [*mail_agent.needs_them(ctx), *mail_agent.to_chase(ctx)]
    missing = []
    for line in text.splitlines():
        if not BULLET.match(line) or citations.MARKER.search(line):
            continue
        said = line.lower()
        for row in plate:
            subject = REPLY_PREFIX.sub("", row["subject"] or "").strip().lower()
            if len(subject) >= SUBJECT_MATCH_FROM and subject in said:
                missing.append(
                    f"- {citations.mark(citations.MAIL, row['id'])} for: {line.strip()[:80]}"
                )
                break
    return missing


def saved_in(ctx: Context, turn: int) -> bool:
    return bool(ctx.bus.db.fetch_all("SELECT 1 FROM brief_artifacts WHERE turn=?", (turn,)))


def current_layer(ctx: Context) -> str:
    """The brief on Today now, so the next one carries on from it rather than starting over."""
    brief = latest(ctx)
    if not brief:
        return "There's no brief yet. This is the first one."
    lines = [f"Written {brief['created']}."]
    if brief["rating"]:
        lines.append(f"They {'liked' if brief['rating'] == 'up' else 'disliked'} it.")
    if brief["comment"]:
        lines.append(f"They said: {brief['comment']}")
    return " ".join(lines) + "\n" + untrusted(brief["text"])


def latest(ctx: Context) -> Any:
    account = accounts.current_account(ctx.config)
    rows = ctx.bus.db.fetch_all(
        "SELECT a.*,f.rating,f.comment FROM brief_artifacts a LEFT JOIN brief_artifact_feedback f ON f.artifact=a.id WHERE a.account=? ORDER BY a.created DESC,a.id DESC LIMIT 1",
        (account,),
    )
    return rows[0] if rows else None
