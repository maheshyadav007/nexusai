"""Know-how an agent loads when it needs it, in the open SKILL.md format.

Only a skill's name and description sit in the prompt. The body comes in with load_skill, and its
other files with read_skill_file. Skills that ship with the app are trusted. The person's own are
proposed, reviewed in full, and pinned to the exact content they approved: a change on disk turns
the skill off until it's approved again. A skill is text. Nothing in it ever runs, and it never
gives an agent a tool it doesn't already have.
"""

import hashlib
import io
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from nexusai.contracts.agent import Skill as SkillView
from nexusai.contracts.agent import SkillFile, SkillList, SkillProposal
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import cards

MIGRATION = Migration(
    "agent_skills_001",
    """
CREATE TABLE skill_approvals (
  name TEXT PRIMARY KEY, hash TEXT NOT NULL, source TEXT NOT NULL, approved TEXT NOT NULL);
CREATE TABLE skill_proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL,
  agents TEXT NOT NULL, needs_tools TEXT NOT NULL, files TEXT NOT NULL, source TEXT NOT NULL,
  hash TEXT NOT NULL, flags TEXT NOT NULL, status TEXT NOT NULL, proposed_by TEXT NOT NULL,
  created TEXT NOT NULL, decided TEXT);
CREATE TABLE skill_loads (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, turn INTEGER, agent TEXT NOT NULL,
  skill TEXT NOT NULL, hash TEXT NOT NULL, time TEXT NOT NULL);
CREATE INDEX skill_loads_skill ON skill_loads (skill, id);
""",
)
ENTRY = "SKILL.md"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv", ".py", ".js", ".sh", ""}
MOST_FILES = 50
MOST_BYTES = 1_000_000
MOST_FILE_CHARS = 50_000
FETCH_SECONDS = 20
# Signs that text is trying to steer the agent rather than teach it. Shown on review, not blocked:
# the person reads the whole skill and decides.
WARNINGS = (
    (
        re.compile(
            r"ignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions|rules)", re.I
        ),
        "Tells the agent to ignore its instructions",
    ),
    (re.compile(r"\b(?:system prompt|developer message)\b", re.I), "Talks about the system prompt"),
    (
        re.compile(r"\b(?:api[_ -]?key|password|token|secret|credential)s?\b", re.I),
        "Mentions keys, passwords or tokens",
    ),
    (
        re.compile(
            r"\b(?:forward|send|email|post|upload)\b[^.\n]{0,60}\b(?:to|at)\b[^.\n]{0,40}@", re.I
        ),
        "Asks to send something to an address",
    ),
    (
        re.compile(r"\b(?:curl|wget|invoke-webrequest|base64)\b", re.I),
        "Mentions downloading or encoding data",
    ),
    (re.compile(r"<!--.*?-->", re.DOTALL), "Has hidden HTML comments"),
    (re.compile("[​-‏ -‮⁠-⁤﻿]"), "Has invisible characters"),
    (
        re.compile(
            r"\b(?:memory|preferences|skill)s?\b[^.\n]{0,40}\b(?:save|write|update|change)\b", re.I
        ),
        "Asks to change memory, preferences or skills",
    ),
)
LINK = re.compile(r"https?://[^\s<>\")\]]+")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    agents: tuple[str, ...]
    needs_tools: tuple[str, ...]
    body: str
    files: dict[str, str]
    origin: str
    hash: str
    active: bool = True
    problem: str | None = None
    version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def digest(files: dict[str, str]) -> str:
    joined = "\n".join(f"{path}\n{files[path]}" for path in sorted(files))
    return hashlib.sha256(joined.encode()).hexdigest()


def parse(files: dict[str, str], origin: str, source_hash: str | None = None) -> Skill:
    """A skill from its files. Raises ValueError with what's wrong, in words for the person."""
    text = files.get(ENTRY)
    if text is None:
        raise ValueError(f"A skill needs a {ENTRY} file.")
    match = FRONT.match(text.lstrip("﻿"))
    if not match:
        raise ValueError(f"{ENTRY} must start with --- and a name and description.")
    try:
        raw = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        raise ValueError(f"Its header isn't valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("Its header must be a list of fields.")
    name = str(raw.get("name", "")).strip()
    description = " ".join(str(raw.get("description", "")).split())
    if not NAME.match(name):
        raise ValueError("Its name must be lowercase letters, numbers and dashes, up to 64.")
    if not description or len(description) > 1024:
        raise ValueError("It needs a description of up to 1024 characters.")
    agents = raw.get("agents", ["session"])
    agents = ("all",) if agents == "all" else tuple(str(item) for item in agents or ())
    needs = tuple(str(item) for item in raw.get("needs_tools", ()) or ())
    return Skill(
        name=name,
        description=description,
        agents=agents or ("session",),
        needs_tools=needs,
        body=match.group(2).strip(),
        files=files,
        origin=origin,
        hash=source_hash or digest(files),
        version=str(raw.get("version", "")),
    )


def _read_folder(folder: Any) -> dict[str, str]:
    found: dict[str, str] = {}

    def walk(node: Any, prefix: str) -> None:
        for entry in sorted(node.iterdir(), key=lambda item: item.name):
            path = f"{prefix}{entry.name}"
            if entry.is_dir():
                walk(entry, f"{path}/")
            elif PurePosixPath(entry.name).suffix.lower() in TEXT_SUFFIXES:
                try:
                    found[path] = entry.read_text("utf-8")
                except (UnicodeDecodeError, OSError):
                    continue

    walk(folder, "")
    return found


def _home_folder(ctx: Context) -> Path:
    return ctx.config.home / "skills"


def all_skills(ctx: Context) -> dict[str, Skill]:
    """Shipped skills, then the person's. A shipped name can't be taken by another skill."""
    found: dict[str, Skill] = {}
    shipped = resources.files(__package__).joinpath("shipped_skills")
    for folder in sorted(shipped.iterdir(), key=lambda item: item.name):
        if folder.is_dir():
            skill = parse(_read_folder(folder), "built_in")
            found[skill.name] = skill
    approved = {
        row["name"]: row["hash"] for row in ctx.bus.db.fetch_all("SELECT * FROM skill_approvals")
    }
    home = _home_folder(ctx)
    if home.is_dir():
        for folder in sorted(home.iterdir()):
            if not folder.is_dir() or folder.is_symlink():
                continue
            files = _read_folder(folder)
            try:
                skill = parse(files, "yours")
            except ValueError as error:
                found[folder.name] = Skill(
                    folder.name, "", (), (), "", files, "yours", digest(files), False, str(error)
                )
                continue
            if skill.name in found:
                continue
            if approved.get(skill.name) != skill.hash:
                skill = Skill(
                    **{
                        **skill.__dict__,
                        "active": False,
                        "problem": "It changed since you approved it, so it's off until you approve it again.",
                    }
                )
            found[skill.name] = skill
    return found


def _allowed_tools(agent: str, db: Database) -> frozenset[str] | None:
    from nexusai.modules.agent import tools

    return tools.allowed_for(cards.engine(db, agent), cards.PERSON, False)


def can_load(db: Database, skill: Skill, agent: str) -> bool:
    if not skill.active:
        return False
    found = cards.card(db, agent)
    ids = {agent, found.engine if found is not None else agent}
    if "all" not in skill.agents and not ids & set(skill.agents):
        return False
    allowed = _allowed_tools(agent, db)
    return allowed is None or set(skill.needs_tools) <= allowed


def available(ctx: Context, agent: str) -> list[Skill]:
    return [skill for skill in all_skills(ctx).values() if can_load(ctx.bus.db, skill, agent)]


def index(ctx: Context, agent: str) -> list[str]:
    """What sits in the prompt: one line per skill, so it's cheap and changes only with skills."""
    return [f"{skill.name}: {skill.description}" for skill in available(ctx, agent)]


def load(ctx: Context, session: str, agent: str, name: str) -> str:
    skill = all_skills(ctx).get(name.strip())
    if skill is None or not can_load(ctx.bus.db, skill, agent):
        names = ", ".join(s.name for s in available(ctx, agent)) or "none"
        return f"No skill called {name} is available to you. Yours: {names}."
    turns = ctx.bus.db.fetch_all(
        "SELECT id FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
        (session,),
    )
    with ctx.bus.db.transaction() as tx:
        tx.execute(
            "INSERT INTO skill_loads (session, turn, agent, skill, hash, time) VALUES (?, ?, ?, ?, ?, ?)",
            (session, turns[0]["id"] if turns else None, agent, skill.name, skill.hash, _now()),
        )
    others = sorted(path for path in skill.files if path != ENTRY)
    more = (
        "\n\nMore files in this skill, read with read_skill_file when a step needs them: "
        + ", ".join(others)
        if others
        else ""
    )
    body = cards.fill(ctx.bus.db, skill.body, agent)
    return f"Skill {skill.name} loaded. Follow it where it applies.\n\n{body}{more}"


def read_file(ctx: Context, agent: str, name: str, path: str) -> str:
    skill = all_skills(ctx).get(name.strip())
    if skill is None or not can_load(ctx.bus.db, skill, agent):
        return f"No skill called {name} is available to you."
    wanted = str(PurePosixPath(path.strip().lstrip("/")))
    if ".." in PurePosixPath(wanted).parts or wanted not in skill.files:
        files = ", ".join(sorted(skill.files)) or "none"
        return f"{name} has no file {path}. Its files: {files}."
    text = skill.files[wanted]
    if len(text) > MOST_FILE_CHARS:
        text = text[:MOST_FILE_CHARS] + "\n[Cut here: the file is longer.]"
    return text


# Proposals


def flags(files: dict[str, str]) -> list[str]:
    found: list[str] = []
    for path, text in sorted(files.items()):
        for pattern, label in WARNINGS:
            if pattern.search(text):
                found.append(f"{path}: {label}")
        links = sorted(set(LINK.findall(text)))
        if links:
            found.append(f"{path}: Links to " + ", ".join(links[:10]))
        if PurePosixPath(path).suffix.lower() in {".py", ".js", ".sh"}:
            found.append(f"{path}: A script. It's kept as text and never run")
    return found


def propose(ctx: Context, files: dict[str, str], source: str, by: str) -> SkillProposal:
    if not files:
        raise CommandError("skill.empty", "There's nothing in it to propose.", 422)
    try:
        skill = parse(files, "yours")
    except ValueError as error:
        raise CommandError("skill.invalid", str(error), 422) from error
    existing = all_skills(ctx).get(skill.name)
    if existing is not None and existing.origin == "built_in":
        raise CommandError(
            "skill.name_taken", f"A built-in skill is already called {skill.name}.", 409
        )
    db = ctx.bus.db
    same = db.fetch_all(
        "SELECT id FROM skill_proposals WHERE hash = ? AND status = 'waiting'", (skill.hash,)
    )
    if same:
        return proposal(db, same[0]["id"])
    with ctx.bus.unit_of_work() as work:
        cursor = work.tx.execute(
            "INSERT INTO skill_proposals (name, description, agents, needs_tools, files, source,"
            " hash, flags, status, proposed_by, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', ?, ?)",
            (
                skill.name,
                skill.description,
                json.dumps(list(skill.agents)),
                json.dumps(list(skill.needs_tools)),
                json.dumps(files),
                source,
                skill.hash,
                json.dumps(flags(files)),
                by,
                _now(),
            ),
        )
        work.emit("skills.changed", {}, source="agent", trace_id=ctx.trace_id)
    return proposal(db, int(cursor.lastrowid or 0))


def proposal(db: Database, identifier: int) -> SkillProposal:
    rows = db.fetch_all("SELECT * FROM skill_proposals WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("skill.not_found", "That proposal no longer exists.", 404)
    row = rows[0]
    files = json.loads(row["files"])
    return SkillProposal(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        agents=json.loads(row["agents"]),
        needs_tools=json.loads(row["needs_tools"]),
        source=row["source"],
        files=[SkillFile(path=path, text=files[path]) for path in sorted(files)],
        flags=json.loads(row["flags"]),
        status=row["status"],
        proposed_by=row["proposed_by"],
        created=row["created"],
    )


def decide(ctx: Context, identifier: int, approve: bool) -> SkillProposal:
    db = ctx.bus.db
    found = proposal(db, identifier)
    if found.status != "waiting":
        raise CommandError("skill.decided", f"That proposal was already {found.status}.", 409)
    if approve:
        files = {item.path: item.text for item in found.files}
        skill = parse(files, "yours")
        folder = _home_folder(ctx) / skill.name
        if folder.exists():
            shutil.rmtree(folder)
        for path, text in files.items():
            target = (folder / path).resolve()
            if not target.is_relative_to(folder.resolve()):
                raise CommandError("skill.invalid", f"{path} would land outside the skill.", 422)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, "utf-8")
    with ctx.bus.unit_of_work() as work:
        if approve:
            work.tx.execute(
                "INSERT INTO skill_approvals (name, hash, source, approved) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (name) DO UPDATE SET hash = excluded.hash, source = excluded.source,"
                " approved = excluded.approved",
                (
                    found.name,
                    digest({item.path: item.text for item in found.files}),
                    found.source,
                    _now(),
                ),
            )
        work.tx.execute(
            "UPDATE skill_proposals SET status = ?, decided = ? WHERE id = ?",
            ("approved" if approve else "rejected", _now(), identifier),
        )
        work.emit("skills.changed", {}, source="person", trace_id=ctx.trace_id)
    return proposal(db, identifier)


def approve_current(ctx: Context, name: str) -> None:
    """Approves a skill of the person's again after it changed on disk, as it is now."""
    skill = all_skills(ctx).get(name)
    if skill is None or skill.origin != "yours" or skill.problem and not skill.description:
        raise CommandError("skill.not_found", "There's no skill of yours with that name.", 404)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO skill_approvals (name, hash, source, approved) VALUES (?, ?, 'on disk', ?)"
            " ON CONFLICT (name) DO UPDATE SET hash = excluded.hash, approved = excluded.approved",
            (name, skill.hash, _now()),
        )
        work.emit("skills.changed", {}, source="person", trace_id=ctx.trace_id)


def remove(ctx: Context, name: str) -> None:
    skill = all_skills(ctx).get(name)
    if skill is None or skill.origin != "yours":
        raise CommandError("skill.not_found", "Only your own skills can be removed.", 404)
    folder = _home_folder(ctx) / name
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM skill_approvals WHERE name = ?", (name,))
        work.emit("skills.changed", {}, source="person", trace_id=ctx.trace_id)


def listing(ctx: Context) -> SkillList:
    db = ctx.bus.db
    loads = {
        row["skill"]: (row["n"], row["last"])
        for row in db.fetch_all(
            "SELECT skill, COUNT(*) AS n, MAX(time) AS last FROM skill_loads GROUP BY skill"
        )
    }
    everyone = cards.all_cards(db)
    shown = []
    for skill in all_skills(ctx).values():
        who = (
            sorted(card.name for card in everyone.values() if can_load(db, skill, card.id))
            if skill.active
            else []
        )
        count, last = loads.get(skill.name, (0, None))
        shown.append(
            SkillView(
                name=skill.name,
                description=skill.description,
                origin="yours" if skill.origin == "yours" else "built_in",
                active=skill.active,
                problem=skill.problem,
                agents=who,
                needs_tools=list(skill.needs_tools),
                files=sorted(skill.files),
                body=skill.body,
                loads=count,
                last_loaded=last,
            )
        )
    proposals = [
        proposal(db, row["id"])
        for row in db.fetch_all(
            "SELECT id FROM skill_proposals WHERE status = 'waiting' ORDER BY id DESC"
        )
    ]
    return SkillList(skills=shown, proposals=proposals)


# Fetching


def _get(client: httpx.Client, url: str) -> httpx.Response:
    if urlparse(url).scheme != "https":
        raise CommandError("skill.fetch", "Only https addresses can be fetched.", 422)
    response = client.get(url)
    if response.status_code != 200:
        raise CommandError(
            "skill.fetch", f"{url} answered {response.status_code}, so nothing was fetched.", 422
        )
    if len(response.content) > MOST_BYTES:
        raise CommandError("skill.fetch", "That's larger than a skill should be (1 MB).", 422)
    return response


def _text_files_from_zip(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        entry = min((n for n in names if PurePosixPath(n).name == ENTRY), key=len, default=None)
        if entry is None:
            raise CommandError("skill.invalid", f"The zip has no {ENTRY}.", 422)
        root = str(PurePosixPath(entry).parent)
        found: dict[str, str] = {}
        for name in names[: MOST_FILES * 4]:
            path = PurePosixPath(name)
            if root != "." and not name.startswith(f"{root}/"):
                continue
            relative = str(path.relative_to(root)) if root != "." else name
            if ".." in PurePosixPath(relative).parts or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                found[relative] = archive.read(name).decode("utf-8")
            except UnicodeDecodeError:
                continue
            if len(found) >= MOST_FILES:
                break
        return found


def _github_folder(
    client: httpx.Client, owner: str, repo: str, ref: str, path: str
) -> dict[str, str]:
    found: dict[str, str] = {}

    def walk(folder: str, prefix: str, depth: int) -> None:
        listing = _get(
            client, f"https://api.github.com/repos/{owner}/{repo}/contents/{folder}?ref={ref}"
        ).json()
        for item in listing if isinstance(listing, list) else []:
            if len(found) >= MOST_FILES:
                return
            name = f"{prefix}{item['name']}"
            if item["type"] == "dir" and depth < 3:
                walk(item["path"], f"{name}/", depth + 1)
            elif item["type"] == "file" and PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES:
                try:
                    found[name] = _get(client, item["download_url"]).content.decode("utf-8")
                except UnicodeDecodeError:
                    continue

    walk(path, "", 0)
    return found


def fetch(url: str) -> dict[str, str]:
    """A skill's text files from a SKILL.md address, a GitHub folder or file, or a zip."""
    parsed = urlparse(url.strip())
    with httpx.Client(timeout=FETCH_SECONDS, follow_redirects=True) as client:
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc == "github.com" and len(parts) >= 4 and parts[2] in {"tree", "blob"}:
            owner, repo, kind, ref, *rest = parts
            path = "/".join(rest)
            if kind == "blob":
                if PurePosixPath(path).name == ENTRY:
                    path = str(PurePosixPath(path).parent)
                else:
                    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
                    return {ENTRY: _get(client, raw).text}
            return _github_folder(client, owner, repo, ref, path)
        response = _get(client, url.strip())
        if parsed.path.lower().endswith(".zip") or response.content[:2] == b"PK":
            return _text_files_from_zip(response.content)
        return {ENTRY: response.text}
