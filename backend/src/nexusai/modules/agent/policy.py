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
Action = Literal["read", "write", "command", "send", "data"]


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


@dataclass(frozen=True)
class ToolEntry:
    name: str
    group: str
    label: str
    description: str
    action: Action
    # When it isn't the same as its group, like creating an agent, which runs by itself later.
    default: Literal["off", "ask", "allow"] | None = None


FILES, COMMANDS, MAIL, CATEGORIES, PLANNER, DATA, AGENTS = (
    "Files",
    "Commands",
    "Mail",
    "Categories and rules",
    "Tasks and reminders",
    "Your data",
    "Agents",
)
ASK: Literal["ask"] = "ask"
CONNECTOR_PREFIX = "mcp_"
TOOL_ENTRIES = (
    ToolEntry("list_folder", FILES, "See folders", "List what's in a folder.", "read"),
    ToolEntry("read_file", FILES, "Read files", "Open a file on this computer.", "read"),
    ToolEntry("write_file", FILES, "Write files", "Create or replace a file.", "write"),
    ToolEntry("edit_file", FILES, "Edit files", "Change part of a file.", "write"),
    ToolEntry("move_file", FILES, "Move files", "Move or rename a file.", "write"),
    ToolEntry("delete_file", FILES, "Delete files", "Remove a file.", "write", ASK),
    ToolEntry(
        "run_command", COMMANDS, "Run commands", "Run a command with your rights.", "command"
    ),
    ToolEntry("search_mail", MAIL, "Search mail", "Find mail and attachments.", "read"),
    ToolEntry("read_thread", MAIL, "Read mail", "Open a conversation.", "read"),
    ToolEntry(
        "read_recipients",
        MAIL,
        "See who mail went to",
        "Look through a message's recipients.",
        "read",
    ),
    ToolEntry("list_mail", MAIL, "List mail", "See what's in a folder or category.", "read"),
    ToolEntry("update_mail", MAIL, "Organize mail", "File, flag, mark and archive mail.", "data"),
    ToolEntry("trash_mail", MAIL, "Delete mail", "Move mail to Trash.", "data", ASK),
    ToolEntry("list_drafts", MAIL, "See drafts", "Read your saved drafts.", "read"),
    ToolEntry("save_draft", MAIL, "Write drafts", "Create or change a draft.", "data"),
    ToolEntry("delete_drafts", MAIL, "Delete drafts", "Remove saved drafts.", "data"),
    ToolEntry("send_mail", MAIL, "Send mail", "Sending always shows you the mail first.", "send"),
    ToolEntry("list_categories", CATEGORIES, "See categories", "See your mail categories.", "read"),
    ToolEntry("create_categories", CATEGORIES, "Create categories", "Add categories.", "data"),
    ToolEntry(
        "update_category",
        CATEGORIES,
        "Change categories",
        "Rename one, set its rule, or show it in the Priority inbox.",
        "data",
    ),
    ToolEntry(
        "merge_categories", CATEGORIES, "Merge categories", "Fold categories into one.", "data"
    ),
    ToolEntry("reorder_categories", CATEGORIES, "Reorder categories", "Set their order.", "data"),
    ToolEntry(
        "delete_categories", CATEGORIES, "Remove categories", "Mail stays, unlabeled.", "data"
    ),
    ToolEntry("list_rules", CATEGORIES, "See rules", "Read your mail rules.", "read"),
    ToolEntry("save_rule", CATEGORIES, "Write rules", "Create or change a mail rule.", "data"),
    ToolEntry("delete_rules", CATEGORIES, "Remove rules", "Delete mail rules.", "data"),
    ToolEntry("list_tasks", PLANNER, "See tasks", "Read your task list.", "read"),
    ToolEntry("create_tasks", PLANNER, "Add tasks", "Add tasks when you ask.", "data"),
    ToolEntry("update_tasks", PLANNER, "Change tasks", "Edit or finish tasks.", "data"),
    ToolEntry("delete_tasks", PLANNER, "Remove tasks", "Delete tasks.", "data"),
    ToolEntry("list_reminders", PLANNER, "See reminders", "Read your reminders.", "read"),
    ToolEntry("create_reminders", PLANNER, "Set reminders", "Set reminders when you ask.", "data"),
    ToolEntry("update_reminders", PLANNER, "Change reminders", "Reschedule or snooze.", "data"),
    ToolEntry("delete_reminders", PLANNER, "Remove reminders", "Delete reminders.", "data"),
    ToolEntry("search_documents", DATA, "Search documents", "Find a document.", "read"),
    ToolEntry("list_documents", DATA, "List documents", "See documents and folders.", "read"),
    ToolEntry("read_document", DATA, "Read documents", "Open a document's text.", "read"),
    ToolEntry("update_documents", DATA, "Organize documents", "Move or tag documents.", "data"),
    ToolEntry(
        "delete_documents", DATA, "Remove documents", "Delete uploaded documents.", "data", ASK
    ),
    ToolEntry(
        "semantic_search", DATA, "Search by meaning", "Find mail and documents by topic.", "read"
    ),
    ToolEntry("read_database", DATA, "Look up data", "Answer questions from your data.", "read"),
    ToolEntry("list_memory", DATA, "See memory", "Read what's remembered.", "read"),
    ToolEntry("update_memory", DATA, "Change memory", "Edit something remembered.", "data"),
    ToolEntry("forget_memory", DATA, "Forget", "Remove something remembered.", "data"),
    ToolEntry("list_panels", DATA, "See panels", "Read your panels.", "read"),
    ToolEntry("save_panel", DATA, "Write panels", "Create or change a panel.", "data"),
    ToolEntry("remove_panels", DATA, "Remove panels", "Delete panels.", "data"),
    ToolEntry("list_agents", AGENTS, "See agents", "See your scheduled agents.", "read"),
    ToolEntry(
        "create_agent", AGENTS, "Create agents", "Make an agent that runs by itself.", "data", ASK
    ),
    ToolEntry(
        "update_agent", AGENTS, "Change agents", "Edit, pause or resume an agent.", "data", ASK
    ),
    ToolEntry("run_agent", AGENTS, "Run agents", "Start an agent now.", "data"),
    ToolEntry("remove_agents", AGENTS, "Remove agents", "Delete scheduled agents.", "data", ASK),
    ToolEntry(
        "save_personal_prompt",
        AGENTS,
        "Save your prompts",
        "Write what it learned from you into your personal prompts.",
        "data",
        ASK,
    ),
)
TOOLS_BY_NAME = {entry.name: entry for entry in TOOL_ENTRIES}


def tool_level(permissions: Permissions, entry: ToolEntry) -> Literal["off", "ask", "allow"]:
    """What this tool is set to: its own setting, its default, or its group's."""
    chosen = permissions.tools.get(entry.name) or entry.default
    if chosen:
        return chosen
    if entry.action == "send":
        return "ask"
    group: Literal["off", "ask", "allow"] = getattr(permissions, entry.action)
    return group


def can_remember(tool: str, untrusted: bool) -> bool:
    """Whether "for this session" can hold. Mail in a session could be what's asking, so a session
    that read mail can only be granted changes to the person's own data, which are easily undone.
    Commands, files and anything that runs later still ask every time."""
    entry = TOOLS_BY_NAME.get(tool)
    if entry is None or entry.action == "send":
        return False
    if not untrusted:
        return True
    return entry.action == "data" and entry.default is None


def for_tool(permissions: Permissions, tool: str) -> Permissions:
    """The permissions a decision should see, with this tool's setting in place of its group's."""
    if tool.startswith(CONNECTOR_PREFIX):
        # New tools from outside ask first, until the person says otherwise.
        return permissions.model_copy(update={"data": permissions.tools.get(tool) or ASK})
    entry = TOOLS_BY_NAME.get(tool)
    if entry is None or entry.action == "send":
        return permissions
    return permissions.model_copy(update={entry.action: tool_level(permissions, entry)})


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
    if action == "data":
        if permissions.data == "off":
            return Decision("deny", "This is turned off in Settings.")
        if session_allowed:
            return Decision("allow", "You allowed this for this session.")
        if untrusted:
            return Decision(
                "ask", "This session has read mail or documents, so changes ask you first."
            )
        if session_allowed or permissions.data == "allow":
            return Decision("allow", "Allowed by your settings.")
        return Decision("ask", "This asks first, by your settings.")
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
