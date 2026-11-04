"""A versioned prompt-feedback loop. Observations never become policy without approval."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.agent import Preference, SavePreference
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context

MIGRATION = Migration(
    "agent_personalization_001",
    """
ALTER TABLE mail_feedback ADD COLUMN event_id TEXT;
ALTER TABLE mail_feedback ADD COLUMN old_value TEXT;
CREATE UNIQUE INDEX mail_feedback_event ON mail_feedback(event_id);
CREATE TABLE interaction_events (
 id TEXT PRIMARY KEY, time TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
 account TEXT, artifact TEXT NOT NULL, artifact_id TEXT NOT NULL, version TEXT,
 run INTEGER, old_value TEXT, new_value TEXT, origin TEXT NOT NULL, undo_of TEXT);
CREATE INDEX interaction_artifact ON interaction_events(artifact,artifact_id,time);
CREATE TABLE preferences (
 id INTEGER PRIMARY KEY, purpose TEXT NOT NULL, account TEXT, sender TEXT, topic TEXT,
 instruction TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
 evidence TEXT NOT NULL, expires_at TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE preference_versions (
 id INTEGER PRIMARY KEY, preference INTEGER NOT NULL, revision INTEGER NOT NULL,
 snapshot TEXT NOT NULL, time TEXT NOT NULL, UNIQUE(preference,revision));
CREATE TABLE prompt_versions (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
 time TEXT NOT NULL);
""",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def observe(
    ctx: Context,
    action: str,
    artifact: str,
    identifier: str,
    *,
    account: str | None = None,
    version: str | None = None,
    run: int | None = None,
    old: Any = None,
    new: Any = None,
    origin: str = "person",
    event_id: str | None = None,
    undo_of: str | None = None,
) -> str:
    identifier_event = event_id or uuid.uuid4().hex
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO interaction_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier_event,
                now(),
                ctx.actor,
                action,
                account,
                artifact,
                identifier,
                version,
                run,
                json.dumps(old),
                json.dumps(new),
                origin,
                undo_of,
            ),
        )
    return identifier_event


def _view(row: Any) -> Preference:
    values = dict(row)
    values["evidence"] = json.loads(values["evidence"])
    if values["status"] == "active" and values["expires_at"] and values["expires_at"] < now():
        values["status"] = "expired"
    return Preference.model_validate(values)


def listing(ctx: Context) -> list[Preference]:
    return [
        _view(row)
        for row in ctx.bus.db.fetch_all("SELECT * FROM preferences ORDER BY updated DESC, id DESC")
    ]


def save(ctx: Context, value: SavePreference, *, proposed: bool = False) -> Preference:
    with ctx.bus.unit_of_work() as work:
        old = (
            work.tx.execute("SELECT * FROM preferences WHERE id = ?", (value.id,)).fetchone()
            if value.id
            else None
        )
        if value.id and not old:
            raise CommandError("preference.not_found", "That preference no longer exists.", 404)
        if old and old["revision"] != value.revision:
            raise CommandError(
                "preference.changed", "This preference changed. Reload before saving.", 409
            )
        revision = old["revision"] + 1 if old else 1
        stamp = now()
        status = "proposed" if proposed else value.status
        fields = (
            value.purpose,
            value.account,
            value.sender.lower() if value.sender else None,
            value.topic,
            value.instruction.strip(),
            status,
            revision,
            json.dumps(value.evidence),
            value.expires_at,
            stamp,
        )
        if old:
            work.tx.execute(
                "UPDATE preferences SET purpose=?, account=?, sender=?, topic=?, instruction=?, status=?, revision=?, evidence=?, expires_at=?, updated=? WHERE id=?",
                (*fields, value.id),
            )
            identifier = int(value.id or 0)
        else:
            cursor = work.tx.execute(
                "INSERT INTO preferences(purpose,account,sender,topic,instruction,status,revision,evidence,expires_at,updated,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*fields, stamp),
            )
            identifier = int(cursor.lastrowid or 0)
        row = work.tx.execute("SELECT * FROM preferences WHERE id=?", (identifier,)).fetchone()
        result = _view(row)
        work.tx.execute(
            "INSERT INTO preference_versions(preference,revision,snapshot,time) VALUES(?,?,?,?)",
            (identifier, revision, result.model_dump_json(), stamp),
        )
        work.emit("preferences.changed", {"id": identifier}, source="agent", trace_id=ctx.trace_id)
    return result


def layer(
    ctx: Context, agent: str, task: str, account: str | None, exclude_id: int | None = None
) -> str:
    purpose = {"mail": "mail", "draft-reply": "draft", "daily-prep": "brief"}.get(agent, "all")
    relevant = []
    for item in listing(ctx):
        if item.id == exclude_id:
            continue
        if item.status != "active" or (item.account and item.account != account):
            continue
        if agent != "session" and item.purpose not in {"all", purpose}:
            continue
        if item.sender and item.sender.casefold() not in task.casefold():
            continue
        if item.topic and item.topic.casefold() not in task.casefold():
            continue
        scope = (
            ", ".join(x for x in (item.purpose, item.account, item.sender, item.topic) if x)
            or "general"
        )
        relevant.append(
            f"[preference:{item.id} version:{item.revision}; updated:{item.updated}; {scope}] {item.instruction}"
        )
    return (
        "Approved, scoped instructions from the person, newest first. Resolve genuine conflicts by explicit scope and recency; if context does not resolve a conflict, ask rather than silently generalizing:\n"
        + "\n".join(relevant)
        if relevant
        else ""
    )


def propose_from_correction(
    ctx: Context, sender: str, field: str, value: str, account: str, evidence: list[str]
) -> None:
    instruction = f"For mail from {sender}, prefer {field} = {value}. Treat a clearly different request as an exception and explain it."
    existing = ctx.bus.db.fetch_all(
        "SELECT 1 FROM preferences WHERE account=? AND sender=? AND instruction=?",
        (account, sender, instruction),
    )
    if existing:
        return
    save(
        ctx,
        SavePreference(
            purpose="mail",
            account=account,
            sender=sender,
            instruction=instruction,
            evidence=evidence,
        ),
        proposed=True,
    )


def save_prompt_version(ctx: Context, kind: str, name: str, content: str) -> None:
    with ctx.bus.db.transaction() as tx:
        last = tx.execute(
            "SELECT content FROM prompt_versions WHERE kind=? AND name=? ORDER BY id DESC LIMIT 1",
            (kind, name),
        ).fetchone()
        if not last or last["content"] != content:
            tx.execute(
                "INSERT INTO prompt_versions(kind,name,content,time) VALUES(?,?,?,?)",
                (kind, name, content, now()),
            )
