"""Decides what a tool may do: allow, ask or refuse. It never runs anything itself."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nexusai.contracts.agent import Permissions
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.home import AGENT_READABLE, AGENT_WRITABLE

MIGRATION = Migration(
    "agent_policy_001",
    """
CREATE TABLE tool_permissions (id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL);
CREATE TABLE session_allowances (session TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY (session, kind));
""",
)
Verdict = Literal["allow", "ask", "deny"]
Action = Literal["read", "write", "command", "send"]


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str


def load_permissions(db: Database) -> Permissions:
    rows = db.fetch_all("SELECT value FROM tool_permissions")
    return Permissions.model_validate(json.loads(rows[0]["value"])) if rows else Permissions()


def save_permissions(db: Database, permissions: Permissions) -> None:
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO tool_permissions (id, value) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET value = excluded.value",
            (permissions.model_dump_json(),),
        )


def allowed_for_session(db: Database, session: str, kind: str) -> bool:
    return bool(
        db.fetch_all(
            "SELECT 1 FROM session_allowances WHERE session = ? AND kind = ?", (session, kind)
        )
    )


def allow_for_session(db: Database, session: str, kind: str) -> None:
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO session_allowances (session, kind) VALUES (?, ?)",
            (session, kind),
        )


def _inside(path: Path, folder: Path) -> bool:
    return path.is_relative_to(folder.resolve())


def _scope(path: Path, home: Path, folders: list[str]) -> str:
    root = home.resolve()
    if _inside(path, root):
        if _inside(path, root / "scratch"):
            return "scratch"
        if any(_inside(path, root / name) for name in AGENT_WRITABLE):
            return "home"
        if any(_inside(path, root / name) for name in AGENT_READABLE):
            return "prompts"
        return "system"
    if any(_inside(path, Path(folder)) for folder in folders):
        return "added"
    return "rest"


def decide(
    action: Action,
    *,
    path: Path | None,
    home: Path,
    permissions: Permissions,
    untrusted: bool,
    session_allowed: bool = False,
) -> Decision:
    """The table in the plan, then the untrusted content rule, which nothing can loosen."""
    if action == "send":
        return Decision("ask", "Sending always needs your approval.")
    if action == "command":
        if permissions.command == "off":
            return Decision("deny", "Commands are turned off in Settings.")
        if untrusted:
            return Decision(
                "ask", "This session has read mail or documents, so commands always ask."
            )
        if session_allowed or permissions.command == "allow":
            return Decision("allow", "Allowed by your settings.")
        return Decision("ask", "Commands ask first, by your settings.")

    assert path is not None
    resolved = path.resolve()
    scope = _scope(resolved, home, permissions.folders)
    setting = permissions.read if action == "read" else permissions.write
    if setting == "off":
        return Decision("deny", f"{action.capitalize()} is turned off in Settings.")
    if scope == "system":
        return Decision("deny", "The agent can't touch NexusAI's system folder.")
    if action == "write" and scope == "prompts":
        return Decision("deny", "Prompts change only through the prompt editor.")
    if action == "write" and untrusted and scope != "scratch":
        return Decision(
            "ask", "This session has read mail or documents, so writes outside scratch always ask."
        )
    if session_allowed:
        return Decision("allow", "You allowed this for the session.")
    if setting == "ask":
        return Decision("ask", "This asks first, by your settings.")
    if action == "read":
        if scope in {"scratch", "home", "prompts", "added"} or permissions.full_computer_access:
            return Decision("allow", "Allowed by your settings.")
        return Decision("ask", "This file is outside your NexusAI Home.")
    if scope in {"scratch", "home"} or permissions.full_computer_access:
        return Decision("allow", "Allowed by your settings.")
    return Decision("ask", "This file is outside your NexusAI Home.")
