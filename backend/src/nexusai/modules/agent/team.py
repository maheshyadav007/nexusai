"""How agents work together: tasks with a contract, asks and answers, reports and verdicts.

One rule decides who runs next: a change to a task sets who must wake, the owner or the assigner,
and the trigger loop starts that run. Every limit here is enforced in code, never by a prompt, and
no agent can raise its own.
"""

import json
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

from nexusai.contracts.agent import (
    OPEN_TASK_STATES,
    AgentCard,
    AgentNow,
    AgentUsage,
    TeamMessage,
    TeamTask,
    TeamTaskView,
)
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import cards
from nexusai.modules.agent.prompt_data import untrusted

MIGRATION = Migration(
    "agent_team_001",
    """
CREATE TABLE team_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  objective TEXT NOT NULL, expected_output TEXT NOT NULL, done_criteria TEXT NOT NULL,
  refs TEXT NOT NULL DEFAULT '[]',
  assigner TEXT NOT NULL, assigner_session TEXT, assigner_turn INTEGER,
  owner TEXT NOT NULL, owner_session TEXT, owner_turn INTEGER,
  parent INTEGER, chain TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL, outcome TEXT, evidence TEXT NOT NULL DEFAULT '[]', verdict TEXT, failure TEXT,
  untrusted INTEGER NOT NULL DEFAULT 0, due TEXT, budget_tokens INTEGER NOT NULL,
  lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, wake TEXT, tool_call TEXT,
  created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX team_tasks_state ON team_tasks (state, id);
CREATE INDEX team_tasks_owner ON team_tasks (owner_session, state);
CREATE UNIQUE INDEX team_tasks_call ON team_tasks (assigner_session, assigner_turn, tool_call);
ALTER TABLE agent_channel ADD COLUMN kind TEXT;
ALTER TABLE agent_channel ADD COLUMN task INTEGER;
ALTER TABLE agent_channel ADD COLUMN sender_agent TEXT;
ALTER TABLE agent_channel ADD COLUMN recipient_agent TEXT;
CREATE INDEX agent_channel_task ON agent_channel (task, id);
""",
)
PERSON = cards.PERSON
TASK_ORIGIN = "task"
# Used when the assigner gives only an objective.
DEFAULT_OUTPUT = "What you did and found, with the ids of everything you changed or looked at."
DEFAULT_DONE = "What the report says changed can be seen with your own tools."
OWNER, ASSIGNER = "owner", "assigner"
CLOSED = {"verified", "rejected", "failed", "canceled"}
# Why a task stopped, in words the map and the person can read.
FAILURES = {
    "ended_without_report": "The run ended without reporting. Review it, then retry or cancel.",
    "run_failed": "The run failed before reporting.",
    "lease_expired": "The run stopped and didn't come back, too many times.",
    "budget": "It used its whole token budget.",
    "due": "It wasn't answered by its due time.",
    "loop": "The two agents kept passing messages back and forth, so it was paused.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _task(row: Any) -> TeamTask:
    return TeamTask(
        id=row["id"],
        objective=row["objective"],
        expected_output=row["expected_output"],
        done_criteria=row["done_criteria"],
        references=json.loads(row["refs"]),
        assigner=row["assigner"],
        owner=row["owner"],
        state=row["state"],
        outcome=row["outcome"],
        evidence=json.loads(row["evidence"]),
        verdict=row["verdict"],
        failure=row["failure"],
        untrusted=bool(row["untrusted"]),
        parent=row["parent"],
        due=row["due"],
        budget_tokens=row["budget_tokens"],
        attempts=row["attempts"],
        owner_session=row["owner_session"],
        assigner_session=row["assigner_session"],
        created=row["created"],
        updated=row["updated"],
    )


def get(db: Database, task: int) -> Any | None:
    rows = db.fetch_all("SELECT * FROM team_tasks WHERE id = ?", (task,))
    return rows[0] if rows else None


def session_task(db: Database, session: str) -> Any | None:
    """The task a session was started for, if it was."""
    rows = db.fetch_all(
        "SELECT * FROM team_tasks WHERE owner_session = ? ORDER BY id DESC LIMIT 1", (session,)
    )
    return rows[0] if rows else None


def _tokens_used(db: Database, session: str | None) -> int:
    if not session:
        return 0
    rows = db.fetch_all(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS n FROM model_calls WHERE session = ?",
        (session,),
    )
    return int(rows[0]["n"])


# Who waits on whom


def waiting_edges(db: Database) -> list[tuple[str, str, int]]:
    """An edge from A to B means A is waiting on B: B owns A's open task, or B was asked by A."""
    edges = []
    for row in db.fetch_all(
        "SELECT id, assigner, owner, state FROM team_tasks WHERE state IN ('queued','working','blocked')"
    ):
        if row["assigner"] != PERSON:
            edges.append((row["assigner"], row["owner"], row["id"]))
    for row in db.fetch_all(
        "SELECT id, assigner, owner FROM team_tasks WHERE state = 'input_required'"
    ):
        # The owner asked its assigner, so the owner waits on the assigner now.
        if row["assigner"] != PERSON:
            edges.append((row["owner"], row["assigner"], row["id"]))
    return edges


def _reaches(edges: list[tuple[str, str, int]], start: str, goal: str) -> bool:
    graph: dict[str, set[str]] = {}
    for source, target, _ in edges:
        graph.setdefault(source, set()).add(target)
    seen, queue = {start}, deque([start])
    while queue:
        node = queue.popleft()
        if node == goal:
            return True
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return False


def _who_waits(db: Database, edges: list[tuple[str, str, int]]) -> str:
    return "; ".join(
        f"{cards.name(db, a)} waits on {cards.name(db, b)} (task {t})" for a, b, t in edges
    )


# Assigning


def assign(ctx: Context, **values: Any) -> str:
    """Checks and saves as one step, so tasks asked for in one reply can't slip past the limits."""
    with ctx.bus.db.serialized():
        return _assign(ctx, **values)


def _assign(
    ctx: Context,
    *,
    session: str,
    sender: str,
    to: str,
    objective: str,
    expected_output: str,
    done_criteria: str,
    references: list[str],
    budget_tokens: int | None,
    due_minutes: int | None,
    tool_call: str,
) -> str:
    db = ctx.bus.db
    team = ctx.config.team
    me = cards.card(db, sender)
    target = cards.resolve(db, to)
    if me is None:
        return "Not assigned: you have no card, so you can't give tasks."
    if target is None:
        # Only those it may give tasks to, so the agent isn't offered a choice that's refused next.
        known = ", ".join(
            found.at for a in me.may_assign_to if (found := cards.card(db, a)) is not None
        )
        return (
            f"Not assigned: no agent is called {to}. You can give tasks to {known}."
            if known
            else f"Not assigned: no agent is called {to}, and you give no tasks. Do it yourself."
        )
    if target.id == me.id:
        return "Not assigned: do this yourself, it's your own work."
    if target.id not in me.may_assign_to:
        allowed = ", ".join(
            found.at for a in me.may_assign_to if (found := cards.card(db, a)) is not None
        )
        return f"Not assigned: you can't give tasks to {target.at}." + (
            f" You may give them to {allowed}." if allowed else " Do the work yourself."
        )
    if "assign" not in target.accepts:
        return f"Not assigned: {target.name} doesn't take tasks."
    missing = [
        label
        for label, value in (
            ("objective", objective),
            ("expected_output", expected_output),
            ("done_criteria", done_criteria),
        )
        if not value.strip()
    ]
    if missing:
        return (
            "Not assigned: a task needs "
            + ", ".join(missing)
            + ". Say what to achieve, what to send back, and how you'll check it's done."
        )
    budget = budget_tokens or team.task_token_budget
    from nexusai.modules.agent import gateway

    if gateway.run_limits_on(ctx) and budget > team.task_token_budget_max:
        return f"Not assigned: the most a task may use is {team.task_token_budget_max} tokens."
    turns = db.fetch_all(
        "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    if not turns:
        return "Not assigned: there's no active run."
    run = turns[0]["id"]
    duplicate = db.fetch_all(
        "SELECT id FROM team_tasks WHERE assigner_session = ? AND assigner_turn = ? AND tool_call = ?",
        (session, run, tool_call),
    )
    if duplicate:
        return f"Already assigned: task {duplicate[0]['id']}."
    given = db.fetch_all(
        "SELECT COUNT(*) AS n FROM team_tasks WHERE assigner_session = ? AND assigner_turn = ?",
        (session, run),
    )[0]["n"]
    if given >= team.assignments_per_run:
        return f"Not assigned: a run may give out {team.assignments_per_run} tasks at most."
    parent = session_task(db, session)
    chain = [*json.loads(parent["chain"]), target.id] if parent else [me.id, target.id]
    if parent is not None:
        if target.id in json.loads(parent["chain"]):
            return (
                f"Not assigned: {target.name} is already part of this task's chain, so it would "
                "come back to them. Finish it yourself, or report what's missing."
            )
        open_children = db.fetch_all(
            "SELECT COUNT(*) AS n FROM team_tasks WHERE parent = ? AND state IN ('queued','working','input_required','blocked')",
            (parent["id"],),
        )[0]["n"]
        if open_children >= team.fan_out:
            return f"Not assigned: this task already has {team.fan_out} open tasks of its own."
    if len(chain) - 1 > team.delegation_depth:
        return (
            f"Not assigned: tasks can be handed on {team.delegation_depth} times at most. "
            "Do this part yourself."
        )
    if _pair_is_busy(ctx, me.id, target.id):
        return (
            f"Not assigned: you and {target.name} have exchanged "
            f"{team.messages_per_pair_per_hour} messages in the last hour, the most allowed."
        )
    edges = waiting_edges(db)
    if _reaches(edges, target.id, me.id):
        return (
            f"Not assigned: {target.name} is already waiting on you, so you would wait on each "
            f"other. {_who_waits(db, edges)}."
        )
    now = _now()
    due = _iso(now + timedelta(minutes=due_minutes or team.task_due_minutes))
    is_untrusted = bool(
        db.fetch_all("SELECT 1 FROM agent_sessions WHERE id = ? AND untrusted = 1", (session,))
    )
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO team_tasks (objective, expected_output, done_criteria, refs, assigner,"
            " assigner_session, assigner_turn, owner, parent, chain, state, untrusted, due,"
            " budget_tokens, wake, tool_call, created, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
            (
                objective.strip(),
                expected_output.strip(),
                done_criteria.strip(),
                json.dumps([str(item) for item in references][:20]),
                me.id,
                session,
                run,
                target.id,
                parent["id"] if parent else None,
                json.dumps(chain),
                int(is_untrusted),
                due,
                budget,
                OWNER,
                tool_call,
                _iso(now),
                _iso(now),
            ),
        )
        task = int(cursor.lastrowid or 0)
        _message(work.tx, task, "assign", me.id, target.id, objective, is_untrusted)
        work.emit("team.changed", {"task": task}, source="agent", trace_id=ctx.trace_id)
    return (
        f"Task {task} given to {target.name} ({target.at}). They start on their own. You'll get a "
        "new message when they report or ask something, so don't wait for it in this run."
    )


def _message(
    tx: Any, task: int | None, kind: str, sender: str, recipient: str | None, text: str, flag: bool
) -> None:
    tx.execute(
        "INSERT INTO agent_channel (sender, recipient, topic, text, time, untrusted, kind, task,"
        " sender_agent, recipient_agent, state)"
        " VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, 'note')",
        (sender, text, _iso(_now()), int(flag), kind, task, sender, recipient),
    )


def _pair_is_busy(ctx: Context, one: str, other: str) -> bool:
    """Two agents talking too much in an hour are stuck, whatever task they talk about."""
    since = _iso(_now() - timedelta(hours=1))
    rows = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS n FROM agent_channel WHERE time >= ? AND ((sender_agent = ? AND"
        " recipient_agent = ?) OR (sender_agent = ? AND recipient_agent = ?))",
        (since, one, other, other, one),
    )
    return int(rows[0]["n"]) >= ctx.config.team.messages_per_pair_per_hour


def _ping_pong(db: Database, task: int, limit: int) -> bool:
    rows = db.fetch_all(
        "SELECT COUNT(*) AS n FROM agent_channel WHERE task = ? AND kind IN ('ask','answer')",
        (task,),
    )
    return int(rows[0]["n"]) >= limit


# Messages on a task


def message(ctx: Context, **values: Any) -> str:
    with ctx.bus.db.serialized():
        return _message_on(ctx, **values)


def _message_on(ctx: Context, *, session: str, sender: str, task: int, kind: str, text: str) -> str:
    db = ctx.bus.db
    row = get(db, task)
    if row is None:
        return f"No task {task}."
    if row["state"] in CLOSED:
        return f"Task {task} is {row['state']}, so nothing more can be said on it."
    text = text.strip()
    if not text:
        return "Say something: the message is empty."
    is_untrusted = bool(
        db.fetch_all("SELECT 1 FROM agent_sessions WHERE id = ? AND untrusted = 1", (session,))
    )
    is_owner = row["owner_session"] == session
    is_assigner = row["assigner_session"] == session
    if _pair_is_busy(ctx, sender, row["assigner"] if is_owner else row["owner"]):
        return (
            f"Not sent: you've exchanged {ctx.config.team.messages_per_pair_per_hour} messages "
            "with them in the last hour, the most allowed. Report what you have instead."
        )
    if kind == "ask":
        if not is_owner:
            return "Only the agent doing the task can ask about it. Use team_assign to ask someone else."
        if row["assigner"] == PERSON:
            return "The person gave this task. Ask them with ask_user instead."
        if _ping_pong(db, task, ctx.config.team.ping_pong_messages):
            _pause_for_loop(ctx, row)
            return "Not sent: you've gone back and forth too often on this task, so it's paused for the person to look at."
        state, wake, recipient = "input_required", ASSIGNER, row["assigner"]
    elif kind == "answer":
        if not is_assigner:
            return "Only the agent that gave the task can answer on it."
        if row["state"] != "input_required":
            return f"Task {task} isn't waiting for an answer. Use note to add something."
        state, wake, recipient = "working", OWNER, row["owner"]
    elif kind == "note":
        if not (is_owner or is_assigner):
            return "Only the two agents on this task can write on it."
        state, wake, recipient = row["state"], None, row["assigner"] if is_owner else row["owner"]
    else:
        return "kind must be ask, answer or note."
    with ctx.bus.unit_of_work() as work:
        _message(work.tx, task, kind, sender, recipient, text, is_untrusted)
        work.tx.execute(
            "UPDATE team_tasks SET state = ?, wake = COALESCE(?, wake), untrusted = MAX(untrusted, ?),"
            " updated = ? WHERE id = ?",
            (state, wake, int(is_untrusted), _iso(_now()), task),
        )
        work.emit("team.changed", {"task": task}, source="agent", trace_id=ctx.trace_id)
    if kind == "ask":
        return "Asked. End this run now: you'll get a new message with the answer."
    if kind == "answer":
        return "Answered. They carry on in their own run."
    return "Noted."


ANSWERED = {"reported", "input_required", "blocked", "failed", "canceled"}
GIVEN = re.compile(r"^Task (\d+) given to ")


def await_result(
    ctx: Context,
    given: str,
    seconds: float,
    stopped: threading.Event | None = None,
    poll: float = 0.5,
) -> str:
    """Waits for a task just given, so a quick job's result comes back in the assigner's own turn.

    The assigner is never woken while its turn is running, so taking the wake-up here is safe:
    whatever this returns, the assigner won't be told again. Past the wait, the task carries on
    and the assigner is woken when it reports, as before. Stop ends the wait at once."""
    found = GIVEN.match(given)
    if found is None or seconds <= 0:
        return given
    task = int(found.group(1))
    db = ctx.bus.db
    stopped = stopped or threading.Event()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stopped.is_set():
        row = get(db, task)
        if row is None:
            return given
        if row["state"] in ANSWERED and row["wake"] == ASSIGNER:
            with ctx.bus.unit_of_work() as work:
                taken = work.tx.execute(
                    "UPDATE team_tasks SET wake = NULL WHERE id = ? AND wake = ?", (task, ASSIGNER)
                ).rowcount
                # What came back is no more trusted than what it was built from.
                if taken and row["untrusted"]:
                    work.tx.execute(
                        "UPDATE agent_sessions SET untrusted = 1 WHERE id = ?",
                        (row["assigner_session"],),
                    )
            if taken:
                return report_text(db, get(db, task) or row)
            return given
        stopped.wait(poll)
    latest = get(db, task)
    owner = cards.name(db, latest["owner"]) if latest is not None else "The agent"
    return (
        f"Task {task} is still being worked on by {owner}. End your turn: you'll get a new "
        "message when it reports or asks something. Tell the person it's in hand."
    )


def _pause_for_loop(ctx: Context, row: Any) -> None:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE team_tasks SET state = 'blocked', failure = 'loop', wake = NULL, updated = ?"
            " WHERE id = ?",
            (_iso(_now()), row["id"]),
        )
        work.emit("team.changed", {"task": row["id"]}, source="agent", trace_id=ctx.trace_id)


# Closing


def close(ctx: Context, **values: Any) -> str:
    with ctx.bus.db.serialized():
        return _close(ctx, **values)


def _close(
    ctx: Context,
    *,
    session: str,
    sender: str,
    task: int,
    action: str,
    outcome: str,
    evidence: list[str],
) -> str:
    db = ctx.bus.db
    row = get(db, task)
    if row is None:
        return f"No task {task}."
    is_owner = row["owner_session"] == session
    is_assigner = row["assigner_session"] == session and not is_owner
    now = _iso(_now())
    if action == "report":
        if not is_owner:
            return "Only the agent doing the task can report it."
        if row["state"] not in {"working", "input_required"}:
            return f"Task {task} is {row['state']}, so it can't be reported now."
        if not outcome.strip():
            return "A report needs an outcome: what you did and what you found."
        limit = ctx.config.team.report_max_chars
        cut = outcome.strip()[:limit]
        if len(outcome.strip()) > limit:
            cut += "\n[Cut at the report limit. Save the rest as an artifact and pass its id.]"
        is_untrusted = bool(
            db.fetch_all("SELECT 1 FROM agent_sessions WHERE id = ? AND untrusted = 1", (session,))
        )
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE team_tasks SET state = 'reported', outcome = ?, evidence = ?, wake = ?,"
                " untrusted = MAX(untrusted, ?), updated = ? WHERE id = ?",
                (cut, json.dumps(evidence[:20]), ASSIGNER, int(is_untrusted), now, task),
            )
            _message(work.tx, task, "report", sender, row["assigner"], cut, is_untrusted)
            work.emit("team.changed", {"task": task}, source="agent", trace_id=ctx.trace_id)
        return "Reported. The agent that gave it will check it. You can end this run."
    if action in {"verify", "reject"}:
        if is_owner:
            return "You did this task, so someone else must check it."
        if not is_assigner:
            return "Only the agent that gave the task can verify or reject it."
        if row["state"] != "reported":
            return (
                f"Task {task} is {row['state']}. Only a reported task can be verified or rejected."
            )
        state = "verified" if action == "verify" else "rejected"
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "UPDATE team_tasks SET state = ?, verdict = ?, wake = NULL, updated = ? WHERE id = ?",
                (state, outcome.strip()[:2000] or None, now, task),
            )
            _message(work.tx, task, action, sender, row["owner"], outcome.strip() or state, False)
            work.emit("team.changed", {"task": task}, source="agent", trace_id=ctx.trace_id)
        return f"Task {task} {state}."
    if action == "cancel":
        if not is_assigner:
            return "Only the agent that gave the task, or the person, can cancel it."
        return cancel(ctx, task, sender, outcome)
    return "action must be report, verify, reject or cancel."


def cancel(ctx: Context, task: int, by: str, why: str = "") -> str:
    row = get(ctx.bus.db, task)
    if row is None:
        raise CommandError("task.not_found", "That task no longer exists.", 404)
    if row["state"] in CLOSED:
        return f"Task {task} was already {row['state']}."
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE team_tasks SET state = 'canceled', verdict = ?, wake = NULL, updated = ? WHERE id = ?",
            (why.strip()[:2000] or None, _iso(_now()), task),
        )
        _message(work.tx, task, "cancel", by, row["owner"], why.strip() or "Canceled.", False)
        work.emit("team.changed", {"task": task}, source="agent", trace_id=ctx.trace_id)
    return f"Task {task} canceled."


def retry(ctx: Context, task: int) -> None:
    row = get(ctx.bus.db, task)
    if row is None:
        raise CommandError("task.not_found", "That task no longer exists.", 404)
    if row["state"] not in {"blocked", "failed", "rejected"}:
        raise CommandError(
            "task.not_retryable", "Only a blocked, failed or rejected task can be retried.", 409
        )
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "UPDATE team_tasks SET state = 'queued', failure = NULL, attempts = 0, wake = ?,"
            " owner_session = NULL, owner_turn = NULL, due = ?, updated = ? WHERE id = ?",
            (
                OWNER,
                _iso(_now() + timedelta(minutes=ctx.config.team.task_due_minutes)),
                _iso(_now()),
                task,
            ),
        )
        work.emit("team.changed", {"task": task}, source="person", trace_id=ctx.trace_id)


def note_from_person(ctx: Context, task: int, text: str) -> None:
    row = get(ctx.bus.db, task)
    if row is None:
        raise CommandError("task.not_found", "That task no longer exists.", 404)
    if row["state"] in CLOSED:
        raise CommandError("task.closed", f"That task is {row['state']}.", 409)
    with ctx.bus.unit_of_work() as work:
        _message(work.tx, task, "note", PERSON, row["owner"], text.strip(), False)
        # Delivered at its next run. A waiting or blocked task starts again with it.
        work.tx.execute(
            "UPDATE team_tasks SET wake = ?, state = CASE WHEN state = 'blocked' THEN 'working' ELSE state END,"
            " failure = CASE WHEN state = 'blocked' THEN NULL ELSE failure END, updated = ? WHERE id = ?",
            (OWNER, _iso(_now()), task),
        )
        work.emit("team.changed", {"task": task}, source="person", trace_id=ctx.trace_id)


def take_notes(ctx: Context, session: str) -> str:
    """Notes for the task this session is doing that it hasn't seen yet, delivered at its next
    step. Once seen here, the task needn't wake for them after the run."""
    db = ctx.bus.db
    row = session_task(db, session)
    if row is None or row["state"] in CLOSED:
        return ""
    rows = db.fetch_all(
        "SELECT id, sender_agent, text, untrusted, read_by FROM agent_channel"
        " WHERE task = ? AND kind = 'note' AND recipient_agent = ? ORDER BY id",
        (row["id"], row["owner"]),
    )
    fresh = [r for r in rows if session not in json.loads(r["read_by"] or "[]")]
    if not fresh:
        return ""
    with db.transaction() as tx:
        for note in fresh:
            seen = [*json.loads(note["read_by"] or "[]"), session]
            tx.execute(
                "UPDATE agent_channel SET read_by = ? WHERE id = ?", (json.dumps(seen), note["id"])
            )
        tx.execute(
            "UPDATE team_tasks SET wake = NULL WHERE id = ? AND wake = ?", (row["id"], OWNER)
        )
    lines = "\n".join(
        f"- from {'the person' if n['sender_agent'] == PERSON else cards.name(db, n['sender_agent'])}: {n['text']}"
        for n in fresh
    )
    text = f"New note on task {row['id']}, take it into account:\n{lines}"
    return untrusted(text) if any(n["untrusted"] for n in fresh) else text


# What a run is told


def contract_text(db: Database, row: Any) -> str:
    """The task as the owner sees it: the contract, then everything said on it so far."""
    giver = cards.name(db, row["assigner"]) if row["assigner"] != PERSON else "the person"
    refs = json.loads(row["refs"])
    lines = [
        f"Task {row['id']} from {giver}.",
        f"Objective: {row['objective']}",
        f"Send back: {row['expected_output']}",
        f"Done when: {row['done_criteria']}",
        f"References: {', '.join(refs) if refs else 'none'}",
        f"Budget: {row['budget_tokens']} tokens. Due: {row['due']}.",
        "When it's done, call team_close with action report, an outcome and evidence (ids). If you "
        "can't finish, report what you found and what's missing. If you need something from "
        f"{giver}, use team_message with kind ask, then end the run. Never mark your own work as "
        "verified.",
    ]
    said = _thread(db, row["id"])
    if said:
        lines.append("On this task so far:")
        lines.append(said)
    text = "\n".join(lines)
    return untrusted(text) if row["untrusted"] else text


def report_text(db: Database, row: Any) -> str:
    """What the assigner is told when it wakes for this task."""
    owner = cards.name(db, row["owner"])
    head = {
        "reported": f"{owner} reported task {row['id']}. Check it against its done criteria with your own tools, then call team_close with verify or reject, and tell the person what matters.",
        "input_required": f"{owner} asked a question on task {row['id']}. Answer it with team_message kind answer, or ask the person if only they know.",
        "blocked": f"Task {row['id']} given to {owner} is blocked: {FAILURES.get(row['failure'] or '', row['failure'] or 'see the task')}. Decide whether to retry it yourself, give it again, or tell the person.",
        "failed": f"Task {row['id']} given to {owner} failed: {FAILURES.get(row['failure'] or '', row['failure'] or 'see the task')}. Tell the person if it matters.",
    }.get(row["state"], f"Task {row['id']} changed: {row['state']}.")
    body = "\n".join(
        [
            f"Objective: {row['objective']}",
            f"Done when: {row['done_criteria']}",
            f"Outcome: {row['outcome'] or 'none yet'}",
            f"Evidence: {', '.join(json.loads(row['evidence'])) or 'none'}",
            _done_before_stopping(db, row) if row["state"] in {"blocked", "failed"} else "",
            _thread(db, row["id"]),
        ]
    ).strip()
    return head + "\n" + (untrusted(body) if row["untrusted"] else body)


def _done_before_stopping(db: Database, row: Any) -> str:
    """What the owner's run got done, so the assigner carries on from there instead of redoing it."""
    if not row["owner_session"]:
        return "It didn't start, so nothing was done."
    calls = db.fetch_all(
        "SELECT tool, status FROM tool_calls WHERE session = ? ORDER BY id DESC LIMIT 12",
        (row["owner_session"],),
    )
    if not calls:
        return "Nothing was done before it stopped."
    steps = ", ".join(f"{c['tool']} ({c['status']})" for c in reversed(calls))
    return f"Done before it stopped, oldest first: {steps}. Check what changed before redoing any of it."


def _thread(db: Database, task: int) -> str:
    rows = db.fetch_all(
        "SELECT kind, sender_agent, text FROM agent_channel WHERE task = ? AND kind != 'assign' ORDER BY id",
        (task,),
    )
    return "\n".join(
        f"- {row['kind']} from {cards.name(db, row['sender_agent']) if row['sender_agent'] != PERSON else 'the person'}: {row['text']}"
        for row in rows
    )


# Views


def roster(ctx: Context, running: Any) -> str:
    db = ctx.bus.db
    lines = []
    for card in listing(ctx, running):
        now = card.now
        state = {
            "idle": "free",
            "working": f"working on task {now.task_id}" if now.task_id else "working",
            "waiting": f"waiting on {now.waiting_on}" if now.waiting_on else "waiting",
            "blocked": f"blocked: {now.reason}" if now.reason else "blocked",
            "off": "off",
        }[now.state]
        takes = "takes tasks" if "assign" in card.accepts else "takes no tasks"
        lines.append(f"- {card.name} (@{card.handle}): {card.role} Now {state}; {takes}.")
    return "\n".join(lines) or f"No agents. ({cards.default(db).name} is alone.)"


def inbox(db: Database, agent: str) -> str:
    rows = db.fetch_all(
        "SELECT * FROM team_tasks WHERE (owner = ? OR assigner = ?) AND state NOT IN ('verified','rejected','failed','canceled')"
        " ORDER BY id",
        (agent, agent),
    )
    mine = [r for r in rows if r["owner"] == agent]
    given = [r for r in rows if r["assigner"] == agent]
    lines = []
    if mine:
        lines.append("Tasks you're doing:")
        lines += [f"- {r['id']} ({r['state']}): {r['objective']}" for r in mine]
    for_me = [r for r in given if r["state"] in {"reported", "input_required"}]
    if for_me:
        lines.append("Waiting on you:")
        lines += [
            f"- {r['id']} {'reported, to verify or reject' if r['state'] == 'reported' else 'asked a question'} by {cards.name(db, r['owner'])}: {r['objective']}"
            for r in for_me
        ]
    waiting = [r for r in given if r["state"] in {"queued", "working", "blocked"}]
    if waiting:
        lines.append("You're waiting on:")
        lines += [
            f"- {r['id']} {cards.name(db, r['owner'])} ({r['state']}): {r['objective']}"
            for r in waiting
        ]
    return "\n".join(lines) or "Nothing open: no tasks for you, from you, or waiting on you."


def live_block(db: Database, agent: str) -> str:
    """The changing part of the team block, sent last so it doesn't break the prompt cache."""
    rows = db.fetch_all(
        "SELECT * FROM team_tasks WHERE (owner = ? OR assigner = ?) AND state IN ('queued','working','input_required','blocked','reported')"
        " ORDER BY id LIMIT 10",
        (agent, agent),
    )
    if not rows:
        return ""
    return "Open tasks:\n" + inbox(db, agent)


def listing(ctx: Context, running: Any) -> list[AgentCard]:
    from nexusai.modules.agent import tools

    db = ctx.bus.db
    today = _now().date().isoformat()
    week = (_now() - timedelta(days=7)).date().isoformat()
    out = []
    # The default agent first, then those that take work, then the rest.
    ordered = sorted(
        cards.all_cards(db).values(),
        key=lambda card: (not card.default, "assign" not in card.accepts, card.name.casefold()),
    )
    for card in ordered:
        allowed = tools.allowed_for(card.id, PERSON, False)
        contract = cards.to_contract(card, sorted(allowed) if allowed is not None else [])
        contract.now = _now_for(db, card.id, running)
        usage = db.fetch_all(
            "SELECT COALESCE(SUM(CASE WHEN day = ? THEN input_tokens + output_tokens END), 0) AS today,"
            " COALESCE(SUM(input_tokens + output_tokens), 0) AS week"
            " FROM model_calls WHERE agent = ? AND day >= ?",
            (today, card.id, week),
        )[0]
        counts = {
            row["state"]: row["n"]
            for row in db.fetch_all(
                "SELECT state, COUNT(*) AS n FROM team_tasks WHERE owner = ? GROUP BY state",
                (card.id,),
            )
        }
        sent = db.fetch_all(
            "SELECT COUNT(*) AS n FROM agent_channel WHERE sender_agent = ? AND time >= ?",
            (card.id, today),
        )[0]["n"]
        before_today = int(usage["week"]) - int(usage["today"])
        contract.usage = AgentUsage(
            tokens_today=int(usage["today"]),
            tokens_week=int(usage["week"]),
            tokens_usual_day=before_today // 7,
            messages_today=int(sent),
            tasks_verified=counts.get("verified", 0),
            tasks_rejected=counts.get("rejected", 0),
            tasks_blocked=counts.get("blocked", 0) + counts.get("failed", 0),
        )
        out.append(contract)
    return out


def _now_for(db: Database, agent: str, running: Any) -> AgentNow:
    sessions = db.fetch_all(
        "SELECT id, updated FROM agent_sessions WHERE agent = ? AND status IN ('queued','running') AND archived = 0",
        (agent,),
    )
    live = [row for row in sessions if running(row["id"])]
    if live:
        task = session_task(db, live[0]["id"])
        return AgentNow(
            state="working",
            task_id=task["id"] if task is not None and task["state"] in OPEN_TASK_STATES else None,
            since=live[0]["updated"],
        )
    blocked = db.fetch_all(
        "SELECT id, failure, updated FROM team_tasks WHERE owner = ? AND state = 'blocked' ORDER BY id DESC LIMIT 1",
        (agent,),
    )
    if blocked:
        return AgentNow(
            state="blocked",
            task_id=blocked[0]["id"],
            reason=FAILURES.get(blocked[0]["failure"] or "", blocked[0]["failure"]),
            since=blocked[0]["updated"],
        )
    for source, target, task in waiting_edges(db):
        if source == agent:
            row = get(db, task)
            return AgentNow(
                state="waiting",
                task_id=task,
                waiting_on=target,
                since=row["updated"] if row is not None else None,
            )
    return AgentNow(state="idle")


def task_list(db: Database, open_only: bool) -> list[TeamTask]:
    where = "WHERE state NOT IN ('verified','rejected','failed','canceled')" if open_only else ""
    rows = db.fetch_all(f"SELECT * FROM team_tasks {where} ORDER BY id DESC LIMIT 200")  # noqa: S608
    found = []
    for row in rows:
        task = _task(row)
        task.tokens_used = _tokens_used(db, row["owner_session"])
        found.append(task)
    return found


def view(db: Database, task: int) -> TeamTaskView:
    row = get(db, task)
    if row is None:
        raise CommandError("task.not_found", "That task no longer exists.", 404)
    found = _task(row)
    found.tokens_used = _tokens_used(db, row["owner_session"])
    messages = [
        TeamMessage(
            id=m["id"],
            task_id=m["task"],
            kind=m["kind"] or "note",
            sender=m["sender_agent"] or m["sender"],
            recipient=m["recipient_agent"],
            text=m["text"],
            time=m["time"],
            untrusted=bool(m["untrusted"]),
        )
        for m in db.fetch_all("SELECT * FROM agent_channel WHERE task = ? ORDER BY id", (task,))
    ]
    children = [
        _task(r)
        for r in db.fetch_all("SELECT * FROM team_tasks WHERE parent = ? ORDER BY id", (task,))
    ]
    return TeamTaskView(task=found, messages=messages, children=children)
