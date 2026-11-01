"""Memory as markdown files in Home, so people can read and edit them with anything."""

import re
from datetime import UTC, datetime
from pathlib import Path

from nexusai.contracts.agent import MemoryFile, MemoryProposal
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError

MIGRATION = Migration(
    "agent_memory_001",
    """
CREATE TABLE memory_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, text TEXT NOT NULL, source TEXT, time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending');
""",
)
WORD = re.compile(r"[\w@.-]{3,}", re.UNICODE)


def _root(home: Path) -> Path:
    return home / "memory"


def _safe(home: Path, relative: str) -> Path:
    root = _root(home).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise CommandError("memory.bad_path", "That isn't a memory file.", 422)
    return target


def list_files(home: Path, query: str = "") -> list[MemoryFile]:
    root = _root(home)
    needle = query.lower().strip()
    files = []
    for path in sorted(root.rglob("*.md")) if root.exists() else []:
        relative = path.relative_to(root)
        parts = relative.parts
        level = "agent" if parts[0] == "agents" else "user"
        content = path.read_text("utf-8", errors="replace")
        if needle and needle not in content.lower() and needle not in path.stem.lower():
            continue
        files.append(
            MemoryFile(
                path=relative.as_posix(),
                level=level,
                agent=parts[1] if level == "agent" and len(parts) > 2 else None,
                name=path.stem,
                content=content,
                updated=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            )
        )
    return files


def save_file(
    home: Path, relative: str | None, name: str, level: str, agent: str | None, content: str
) -> str:
    if relative is None:
        folder = f"agents/{agent or 'session'}" if level == "agent" else "user"
        relative = f"{folder}/{name}.md"
    target = _safe(home, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, "utf-8")
    return relative


def remove_file(home: Path, relative: str) -> None:
    _safe(home, relative).unlink(missing_ok=True)


def relevant(home: Path, agent: str, task_text: str, limit: int) -> str:
    """Memories sharing the most words with this task, within the size limit."""
    words = {word.lower() for word in WORD.findall(task_text)}
    scored: list[tuple[int, str, str]] = []
    for file in list_files(home):
        if file.level == "agent" and file.agent != agent:
            continue
        overlap = len(words & {word.lower() for word in WORD.findall(file.content)})
        if overlap or not words:
            scored.append((overlap, file.name, file.content.strip()))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[str] = []
    used = 0
    for _, name, content in scored:
        block = f"[{name}]\n{content}"
        if used + len(block) > limit:
            continue
        chosen.append(block)
        used += len(block)
    return "\n\n".join(chosen)


def propose(db: Database, agent: str, text: str, source: str | None) -> None:
    """Runs that read untrusted content can only suggest a memory, so mail can't plant one."""
    # The same mail can be judged again, and shouldn't ask twice.
    if db.fetch_all(
        "SELECT id FROM memory_proposals WHERE text = ? AND source IS ?", (text, source)
    ):
        return
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO memory_proposals (agent, text, source, time) VALUES (?, ?, ?, ?)",
            (agent, text, source, datetime.now(UTC).isoformat()),
        )


def proposals(db: Database) -> list[MemoryProposal]:
    rows = db.fetch_all("SELECT * FROM memory_proposals WHERE status = 'pending' ORDER BY id")
    return [
        MemoryProposal(
            id=r["id"], agent=r["agent"], text=r["text"], source=r["source"], time=r["time"]
        )
        for r in rows
    ]


def decide_proposal(db: Database, home: Path, proposal: int, accept: bool) -> None:
    rows = db.fetch_all(
        "SELECT * FROM memory_proposals WHERE id = ? AND status = 'pending'", (proposal,)
    )
    if not rows:
        raise CommandError("memory.no_proposal", "That suggestion has already been handled.", 409)
    with db.transaction() as tx:
        tx.execute(
            "UPDATE memory_proposals SET status = ? WHERE id = ?",
            ("accepted" if accept else "declined", proposal),
        )
    if accept:
        save_file(home, None, f"noted-{proposal}", "user", None, f"{rows[0]['text']}\n")
