"""Briefs reach Today only through the brief agent's update_brief, never from what it replies."""

import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context
from nexusai.modules.agent.prompt_data import untrusted
from nexusai.modules.mail import accounts

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
            "SELECT id,subject,status,importance,next_action,follow_up_on,decision_version FROM threads WHERE account=? AND in_trash=0 AND status IN ('waiting_on_you','waiting_on_others') ORDER BY importance='high' DESC,last_date DESC",
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


def save(ctx: Context, session: str, text: str) -> str:
    """The brief agent's update_brief. One brief per run: saving again in the same run replaces it."""
    turns = ctx.bus.db.fetch_all(
        "SELECT id FROM agent_turns WHERE session=? AND closed=0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if not turns:
        return "There's no run to save this brief from."
    turn = turns[0]["id"]
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
            "INSERT INTO brief_artifacts(turn,session,account,text,created,partial,snapshot) VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(turn) DO UPDATE SET text=excluded.text,created=excluded.created,partial=excluded.partial",
            (
                turn,
                session,
                account,
                text.strip(),
                datetime.now(UTC).isoformat(),
                int(bool(pending or coverage.get("partial"))),
                data,
            ),
        )
        work.emit("brief.ready", {"turn": turn}, source="agent", trace_id=ctx.trace_id)
    return "Saved. It's at the top of their Today page now."


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
