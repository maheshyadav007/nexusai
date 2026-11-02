"""What an approval says at a glance, and what's behind it for anyone who wants to look.

Built from the tool's actual arguments, never from anything the model wrote about them. A short
summary mustn't hide what's being approved, so it only says less when that loses nothing.
"""

import re
from pathlib import PurePosixPath

from nexusai.contracts.agent import ApprovalPreview

# One `cat > file <<'END'` and nothing else. The quoted word matters: unquoted, the shell would run
# anything in the text, so that's a command and shows as one. So does anything before or after it.
FILE_WRITE = re.compile(
    r"""\A\s*cat\s*>\s*(?P<path>[^\s;&|<>`$()'"]+)\s*<<-?\s*(?P<quote>['"])(?P<end>\w+)(?P=quote)[ \t]*\n"""
    r"""(?P<body>.*)\n(?P=end)[ \t]*\n?\s*\Z""",
    re.S,
)
SUMMARY_CHARS = 120
LANGUAGES = {
    ".html": "html", ".htm": "html", ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".json": "json", ".css": "css", ".md": "markdown", ".sh": "bash", ".sql": "sql",
    ".yaml": "yaml", ".yml": "yaml", ".xml": "xml", ".csv": "text", ".txt": "text",
}  # fmt: skip
FILE_TOOLS = {"write_file", "edit_file", "move_file", "delete_file"}
MAIL_TOOLS = {
    "send_mail",
    "draft_reply",
    "trash_mail",
    "delete_drafts",
    "update_mail",
    "save_draft",
}
DATA_TOOLS = {
    "create_tasks", "update_tasks", "delete_tasks", "create_reminders", "update_reminders",
    "delete_reminders", "create_categories", "delete_categories", "merge_categories",
    "reorder_categories", "delete_rules", "update_memory", "forget_memory", "propose_memory",
    "save_personal_prompt", "delete_documents", "remove_panels", "remove_agents", "run_agent",
    "suggest", "tell", "notify_person", "use", "write_work_board", "update_category", "save_rule",
    "update_documents", "save_panel", "create_agent", "update_agent",
}  # fmt: skip
# Tools that only read never reach a person, unless their permission was set to ask.
READ_TOOLS = {
    "read_file", "list_folder", "search_mail", "read_thread", "search_documents", "read_document",
    "list_documents", "list_tasks", "list_reminders", "list_categories", "list_rules",
    "list_drafts", "list_memory", "list_panels", "list_agents", "read_database", "semantic_search",
    "read_work_board", "read_agent_messages", "list_mail",
}  # fmt: skip


def _size(text: str) -> str:
    size = len(text.encode())
    return f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} bytes"


def _command(detail: str) -> ApprovalPreview:
    written = FILE_WRITE.match(detail)
    # The end word turning up earlier means the text stopped there, and the rest would run.
    if written and not re.search(rf"^{written['end']}[ \t]*$", written["body"], re.M):
        name = written["path"]
        return ApprovalPreview(
            kind="file",
            summary=f"Create file {PurePosixPath(name).name}, {_size(written['body'])}",
            language=LANGUAGES.get(PurePosixPath(name).suffix.lower(), "text"),
            content=written["body"],
            location=name,
        )
    lines = detail.strip().splitlines() or [""]
    first = lines[0][:SUMMARY_CHARS]
    more = f", {len(lines)} lines" if len(lines) > 1 else ""
    return ApprovalPreview(
        kind="command", summary=f"Run a command: {first}{more}", language="bash", content=detail
    )


def describe(tool: str, summary: str, detail: str) -> ApprovalPreview:
    """One way to show each tool. Anything not named here, like a connector's, stays in full."""
    if tool == "run_command":
        return _command(detail or summary)
    if tool in FILE_TOOLS:
        kind = "file"
    elif tool in MAIL_TOOLS:
        kind = "mail"
    elif tool in DATA_TOOLS or tool in READ_TOOLS:
        kind = "change"
    else:
        kind = "other"
    language = "diff" if tool == "edit_file" else "json" if detail[:1] in "{[" else "text"
    return ApprovalPreview(
        kind=kind, summary=summary[:SUMMARY_CHARS], language=language, content=detail
    )
