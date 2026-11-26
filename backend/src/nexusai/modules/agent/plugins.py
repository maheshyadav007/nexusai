"""Plugins: agents, skills and prompts as files, in Claude Code's plugin layout and names.

A plugin is a folder with a `plugin.json`, `agents/<name>.md` (frontmatter, then the agent's
prompt), `skills/<name>/SKILL.md` and, for what only NexusAI reads, a `nexusai/` folder
(`nexusai/prompts/<name>.md`). Fields Anthropic names keep Anthropic's meaning; ours sit under a
`nexusai` key. The plugins that ship with the app live in `builtin_plugins/` and are read-only.

A built-in plugin that doesn't load is our bug, so it fails start-up and the tests, as a broken
card did. See docs/PLUGIN_FORMAT_PLAN.md.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

import yaml

BUILT_IN = "built_in"
MANIFESTS = ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json")
# Anthropic's rule for plugin names: kebab-case, no spaces, `@`, `:` or path separators.
PLUGIN_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
OPEN = "---\n"
CLOSE = "\n---\n"


@dataclass(frozen=True)
class Plugin:
    name: str
    display_name: str
    version: str
    description: str
    layer: str
    required: bool
    root: Traversable = field(repr=False, compare=False)


@dataclass(frozen=True)
class AgentFile:
    """One agent: Anthropic's fields at the top level, ours under `nexusai`, the prompt below."""

    plugin: str
    name: str
    description: str
    front: dict[str, Any]
    body: str
    hash: str

    @property
    def ours(self) -> dict[str, Any]:
        value = self.front.get("nexusai")
        return value if isinstance(value, dict) else {}


def split(text: str) -> tuple[dict[str, Any], str]:
    """Frontmatter and body. The body is returned byte for byte, since its text is hashed into
    what decides whether mail must be judged again."""
    if not text.startswith(OPEN):
        raise ValueError("doesn't start with --- frontmatter")
    end = text.find(CLOSE, len(OPEN) - 1)
    if end < 0:
        raise ValueError("its frontmatter has no closing ---")
    front = yaml.safe_load(text[len(OPEN) : end + 1]) or {}
    if not isinstance(front, dict):
        raise ValueError("its frontmatter isn't a set of fields")
    return front, text[end + len(CLOSE) :]


def _built_in_root() -> Traversable:
    return resources.files(__package__).joinpath("builtin_plugins")


def _manifest(folder: Traversable) -> dict[str, Any]:
    for relative in MANIFESTS:
        entry = folder.joinpath(*relative.split("/"))
        if entry.is_file():
            raw = json.loads(entry.read_text("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"{relative} isn't a JSON object")
            return raw
    raise ValueError("has no plugin.json")


@cache
def built_in() -> tuple[Plugin, ...]:
    found = []
    for folder in sorted(_built_in_root().iterdir(), key=lambda item: item.name):
        if not folder.is_dir() or folder.name.startswith(("_", ".")):
            continue
        raw = _manifest(folder)
        name = str(raw.get("name", ""))
        if not PLUGIN_NAME.match(name) or name != folder.name:
            raise ValueError(f"Built-in plugin {folder.name} must be named {folder.name}")
        extra = raw.get("nexusai")
        ours: dict[str, Any] = extra if isinstance(extra, dict) else {}
        found.append(
            Plugin(
                name=name,
                display_name=str(raw.get("displayName") or name),
                version=str(raw.get("version", "")),
                description=str(raw.get("description", "")),
                layer=BUILT_IN,
                required=bool(ours.get("required", False)),
                root=folder,
            )
        )
    return tuple(found)


def _entries(plugin: Plugin, *parts: str) -> list[Traversable]:
    folder = plugin.root.joinpath(*parts)
    if not folder.is_dir():
        return []
    return sorted(folder.iterdir(), key=lambda item: item.name)


@cache
def agent_files() -> dict[str, AgentFile]:
    """Every built-in agent by name. A name in two plugins is refused: ids must be unique."""
    found: dict[str, AgentFile] = {}
    for plugin in built_in():
        for entry in _entries(plugin, "agents"):
            if not entry.name.endswith(".md"):
                continue
            where = f"{plugin.name}/agents/{entry.name}"
            text = entry.read_text("utf-8")
            try:
                front, body = split(text)
            except ValueError as error:
                raise ValueError(f"{where} {error}") from error
            name = str(front.get("name", ""))
            if not AGENT_NAME.match(name) or entry.name != f"{name}.md":
                raise ValueError(f"{where} must be named after its name field, {name}.md")
            if not str(front.get("description", "")).strip():
                raise ValueError(f"{where} needs a description")
            if name in found:
                raise ValueError(f"{where}: {found[name].plugin} already has an agent named {name}")
            found[name] = AgentFile(
                plugin=plugin.name,
                name=name,
                description=str(front["description"]).strip(),
                front=front,
                body=body,
                # From the file itself, so it changes whenever the agent does and is never forgotten.
                hash=hashlib.sha256(text.encode()).hexdigest()[:12],
            )
    return found


def plugin_of(name: str) -> str | None:
    found = agent_files().get(name)
    return found.plugin if found else None


def agent_body(name: str) -> str | None:
    found = agent_files().get(name)
    return found.body if found else None


def skill_folders() -> list[Traversable]:
    """Each built-in skill's folder, across plugins, in name order as the old folder was."""
    folders = [
        entry
        for plugin in built_in()
        for entry in _entries(plugin, "skills")
        if entry.is_dir() and not entry.name.startswith(("_", "."))
    ]
    names = [entry.name for entry in folders]
    if len(set(names)) != len(names):
        raise ValueError("Two built-in plugins have a skill with the same name")
    return sorted(folders, key=lambda item: item.name)


@cache
def _prompts() -> dict[str, str]:
    found: dict[str, str] = {}
    for plugin in built_in():
        for entry in _entries(plugin, "nexusai", "prompts"):
            if not entry.name.endswith(".md"):
                continue
            name = entry.name.removesuffix(".md")
            if name in found:
                raise ValueError(f"Two built-in plugins have the prompt {name}")
            found[name] = entry.read_text("utf-8")
    return found


def prompt(name: str) -> str:
    """A prompt only NexusAI reads, such as the Mail agent's text for one kind of run."""
    try:
        return _prompts()[name]
    except KeyError:
        raise FileNotFoundError(f"No built-in plugin has the prompt {name}") from None


def prompt_names() -> set[str]:
    return set(_prompts())


# Where a built-in routine's state lives today: the row that already runs it.
ROUTINE_ROWS = {"agent_triggers": "id", "schedules": "kind"}


@dataclass(frozen=True)
class RoutineFile:
    """A built-in routine: what starts it, which agent does it, and the row that runs it."""

    plugin: str
    name: str
    title: str
    description: str
    agent: str
    triggers: tuple[dict[str, Any], ...]
    table: str
    key: str
    body: str


@cache
def routine_files() -> tuple[RoutineFile, ...]:
    found: list[RoutineFile] = []
    for plugin in built_in():
        for entry in _entries(plugin, "nexusai", "routines"):
            if not entry.name.endswith(".md"):
                continue
            where = f"{plugin.name}/nexusai/routines/{entry.name}"
            try:
                front, body = split(entry.read_text("utf-8"))
            except ValueError as error:
                raise ValueError(f"{where} {error}") from error
            extra = front.get("nexusai")
            ours: dict[str, Any] = extra if isinstance(extra, dict) else {}
            found_row = ours.get("row")
            row: dict[str, Any] = found_row if isinstance(found_row, dict) else {}
            table = str(row.get("table", ""))
            if table not in ROUTINE_ROWS or not row.get(ROUTINE_ROWS[table]):
                raise ValueError(f"{where} needs nexusai.row naming the row that runs it")
            name = str(front.get("name", ""))
            if entry.name != f"{name}.md":
                raise ValueError(f"{where} must be named after its name field, {name}.md")
            agent = str(front.get("agent", ""))
            if agent not in agent_files():
                raise ValueError(f"{where} names an agent that doesn't exist: {agent}")
            found.append(
                RoutineFile(
                    plugin=plugin.name,
                    name=name,
                    title=str(ours.get("title") or name),
                    description=str(front.get("description", "")).strip(),
                    agent=agent,
                    triggers=tuple(t for t in front.get("triggers") or [] if isinstance(t, dict)),
                    table=table,
                    key=str(row[ROUTINE_ROWS[table]]),
                    body=body.strip(),
                )
            )
    return tuple(found)
