"""Memory as markdown files in Home, so people can read and edit them with anything."""

import re
from datetime import UTC, datetime
from pathlib import Path

from nexusai.contracts.agent import MemoryFile, MemoryProposal
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError
from nexusai.modules.agent.prompt_data import untrusted

MIGRATION = Migration(
    "agent_memory_001",
    """
CREATE TABLE memory_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, text TEXT NOT NULL, source TEXT, time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending');
""",
)
WORD = re.compile(r"[\w@.-]{3,}", re.UNICODE)
# What the Mail agent has picked up from mail. Only it reads this, always marked as from mail, so
# a planted email can't reach other agents or give it instructions. The person can edit it.
LEARNED_PATH = "agents/mail/learned.md"
LEARNED_MAX_CHARS = 40_000
LEARNED_NOTE_CHARS = 300
# What the person confirmed of what was learned. It's theirs now, so it's no longer marked as mail.
CONFIRMED_PATH = "user/confirmed.md"
# Mail's notes can't crowd out what the person said themselves.
LEARNED_SHARE = 0.5
SOURCE = re.compile(r" \[mail:\d+\]$")


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


def learned(home: Path) -> str:
    path = _safe(home, LEARNED_PATH)
    return path.read_text("utf-8", errors="replace") if path.exists() else ""


def add_learned(home: Path, notes: list[str], source: int | None = None) -> None:
    add_learned_sources(home, [(note, source) for note in notes])


def add_learned_sources(home: Path, notes: list[tuple[str, int | None]]) -> None:
    """Keep provenance when identical observations came from different conversations."""
    current = learned(home)
    lines = current.splitlines()
    for note, source in notes:
        line = f"- {' '.join(note.split())[:LEARNED_NOTE_CHARS]}"
        if len(line) <= len("- "):
            continue
        sourced = f"{line} [mail:{source}]" if source else line
        matching = [
            index for index, existing in enumerate(lines) if SOURCE.sub("", existing) == line
        ]
        if sourced in lines or (source is None and matching):
            continue
        unscoped = next((index for index in matching if not SOURCE.search(lines[index])), None)
        if source and unscoped is not None:
            lines[unscoped] = sourced
        else:
            lines.append(sourced)
    while len("\n".join(lines)) > LEARNED_MAX_CHARS:
        lines.pop(0)
    if lines != current.splitlines():
        save_file(home, LEARNED_PATH, "", "agent", "mail", "\n".join(lines) + "\n")


def replace_learned(home: Path, content: str) -> None:
    save_file(home, LEARNED_PATH, "", "agent", "mail", content[:LEARNED_MAX_CHARS].strip() + "\n")


def confirmed(home: Path) -> str:
    path = _safe(home, CONFIRMED_PATH)
    return path.read_text("utf-8", errors="replace") if path.exists() else ""


def remove_learned(home: Path, line: str) -> None:
    lines = learned(home).splitlines()
    if line in lines:
        lines.remove(line)
        save_file(home, LEARNED_PATH, "", "agent", "mail", "\n".join(lines) + "\n")
        return
    said = confirmed(home).splitlines()
    if line not in said:
        raise CommandError("memory.no_note", "That note has already gone.", 409)
    said.remove(line)
    save_file(home, CONFIRMED_PATH, "", "user", None, "\n".join(said) + "\n")


def confirm_learned(home: Path, line: str) -> None:
    """The person says it's true, so it moves out of what mail said and into what they said."""
    remove_learned(home, line)
    target = _safe(home, CONFIRMED_PATH)
    before = target.read_text("utf-8") if target.exists() else ""
    save_file(home, CONFIRMED_PATH, "", "user", None, f"{before}{SOURCE.sub('', line)}\n")


def _fit_learned(content: str, words: set[str], limit: int) -> str:
    """All of it if it fits. Otherwise what bears on this email first, and headings to place it."""
    if len(content) <= limit:
        return content
    lines = content.splitlines()
    ranked = sorted(
        range(len(lines)),
        key=lambda i: -len(words & {word.lower() for word in WORD.findall(lines[i])}),
    )
    chosen: set[int] = set()
    used = 0
    for index in ranked:
        used += len(lines[index]) + 1
        if used > limit:
            break
        chosen.add(index)
    return "\n".join(lines[i] for i in sorted(chosen))


def remove_file(home: Path, relative: str) -> None:
    _safe(home, relative).unlink(missing_ok=True)


def relevant(
    home: Path, agent: str, task_text: str, limit: int, include_learned: bool = True
) -> str:
    """Memories sharing the most words with this task, within the size limit."""
    words = {word.lower() for word in WORD.findall(task_text)}
    scored: list[tuple[int, str, str]] = []
    for file in list_files(home):
        if file.level == "agent" and file.agent != agent:
            continue
        overlap = len(words & {word.lower() for word in WORD.findall(file.content)})
        if file.path == CONFIRMED_PATH:
            # Keep individual constraints when the file outgrows the context budget.
            scored.extend(
                (1 << 31, file.name, line.strip())
                for line in file.content.splitlines()
                if line.strip()
            )
        elif file.path == NOTES_PATH:
            # What the agents noted about the person bears on most work, a line at a time.
            scored.extend(
                (1 << 29, file.name, line.strip())
                for line in file.content.splitlines()
                if line.strip()
            )
        elif file.path == LEARNED_PATH:
            if not include_learned:
                continue
            # It's about the person, so it's always relevant, and it's only ever data.
            kept = _fit_learned(file.content.strip(), words, int(limit * LEARNED_SHARE))
            scored.append((1 << 30, file.name, untrusted(kept)))
        elif overlap or not words:
            scored.append((overlap, file.name, file.content.strip()))
    scored.sort(key=lambda item: (-item[0], item[1]))
    # One heading per file, with its chosen lines under it, rather than a heading on every line.
    chosen: dict[str, list[str]] = {}
    used = 0
    for _, name, content in scored:
        cost = len(content) + 1 + (0 if name in chosen else len(name) + 4)
        if used + cost > limit:
            continue
        chosen.setdefault(name, []).append(content)
        used += cost
    return "\n\n".join(f"[{name}]\n" + "\n".join(lines) for name, lines in chosen.items())


# Where facts the agents note down go, one per line, so they stay in one place the person can read.
NOTES_PATH = "user/notes.md"


def _plain(text: str) -> str:
    """The words alone, so case and punctuation don't make the same fact look new."""
    return " ".join(re.findall(r"\w+", text.lower()))


def remember(
    home: Path, db: Database, agent: str, facts: list[str], untrusted: bool, source: str | None
) -> tuple[int, int]:
    """Notes down facts not already known, as notes, or only as proposals after untrusted input.
    Returns how many were new and how many were already known."""
    known = {
        _plain(line.lstrip("- "))
        for file in list_files(home)
        for line in file.content.splitlines()
        if line.strip()
    } | {_plain(row["text"]) for row in db.fetch_all(
        "SELECT text FROM memory_proposals WHERE status = 'pending'"
    )}  # fmt: skip
    new = []
    for fact in (fact.strip() for fact in facts):
        if fact and _plain(fact) and _plain(fact) not in known:
            known.add(_plain(fact))
            new.append(fact)
    if untrusted:
        for fact in new:
            propose(db, agent, fact, source)
    elif new:
        target = _safe(home, NOTES_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = target.read_text("utf-8") if target.exists() else ""
        lines = "".join(f"- {fact}\n" for fact in new)
        target.write_text(
            before + ("" if not before or before.endswith("\n") else "\n") + lines, "utf-8"
        )
    return len(new), len(facts) - len(new)


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
