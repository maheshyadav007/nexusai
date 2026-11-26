"""Assembles the prompt layers for every run, in the same order, top layer winning."""

import os
import platform
import re
import shutil
import sys
from collections.abc import Collection
from importlib import resources
from pathlib import Path

from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.modules.agent import cards, plugins
from nexusai.modules.agent.gateway import Layer

SH_LIKE = frozenset({"bash", "zsh", "sh", "dash", "ksh"})
PERSONAL_ORDER = ("about-me.md", "importance.md", "categories.md", "senders.md", "topics.md")
TOOLS_TO_REPORT = ("python3", "git", "node", "uv")
# A section marked like this under its heading is only for an agent that has one of those tools.
NEEDS = re.compile(r"^<!-- needs: ([a-z_, ]+) -->\n", re.M)


def packaged(name: str) -> str:
    return resources.files(__package__).joinpath("prompts", name).read_text("utf-8")


def posix_shell() -> str:
    """The shell commands run in here, and what the model is told, so its syntax suits it."""
    chosen = os.environ.get("SHELL", "")
    if Path(chosen).name in SH_LIKE and shutil.which(chosen):
        return chosen
    return shutil.which("bash") or shutil.which("zsh") or "/bin/sh"


def system_context(config: Config) -> str:
    """Told once, in the system prompt only, so commands suit this computer."""
    shell = "PowerShell" if sys.platform == "win32" else posix_shell()
    tools = [name for name in TOOLS_TO_REPORT if shutil.which(name)]
    home = config.home
    return "\n".join(
        [
            "This computer:",
            f"- {platform.system()} {platform.release()}, {platform.machine()}",
            f"- Shell: {shell}",
            f"- Installed: {', '.join(tools) or 'unknown'}",
            f"- NexusAI Home: {home}",
            f"- File tools reach {home}/scratch, memory, documents and artifacts by default.",
        ]
    )


def personal_prompts(home: Path) -> str:
    folder = home / "prompts" / "personal"
    if not folder.is_dir():
        return ""
    # Read fresh every run, so edits made outside the app are picked up.
    names = [n for n in PERSONAL_ORDER if (folder / n).exists()]
    names += sorted(p.name for p in folder.glob("*.md") if p.name not in PERSONAL_ORDER)
    return "\n\n".join(
        f"[personal prompt: {Path(name).stem}]\n{(folder / name).read_text('utf-8').strip()}"
        for name in names
    ).strip()


def for_tools(text: str, tools: Collection[str] | None) -> str:
    """Leaves out "## " sections about tools this run doesn't have, so a small model isn't told to
    use what it can't. None keeps every section, for showing the whole prompt."""
    parts = re.split(r"(?m)^(?=## )", text)
    kept = []
    for part in parts:
        needs = NEEDS.search(part)
        if needs and tools is not None:
            wanted = {name.strip() for name in needs.group(1).split(",")}
            if not wanted & set(tools):
                continue
        kept.append(NEEDS.sub("", part))
    return "".join(kept).replace("\n\n\n", "\n\n")


def agent_base(agent: str) -> str:
    """An agent's own prompt: the body of its agent file. Prompts that aren't an agent's, such as
    the summary writer's, are still plain files in prompts/."""
    body = plugins.agent_body(agent)
    return body if body is not None else packaged(f"{agent}.md")


def agent_prompt(home: Path, agent: str) -> str:
    base = agent_base(agent)
    added = home / "prompts" / "agents" / f"{agent}.md"
    return f"{base}\n\n{added.read_text('utf-8').strip()}" if added.exists() else base


def build_layers(
    config: Config,
    agent: str,
    memory: str = "",
    capabilities: str = "",
    about: str = "",
    corrections: str = "",
    mailbox: str = "",
    brief_wishes: str = "",
    db: Database | None = None,
    skills: list[str] | None = None,
    tools: Collection[str] | None = None,
    **values: str,
) -> list[Layer]:
    home = config.home
    # An agent the person made runs with its template's prompt, as itself.
    found = cards.card(db, agent) if db is not None else None
    base = found.engine if found is not None and found.engine else agent
    # Only the known fields are filled in, so braces in someone's own prompt stay as written.
    text = agent_prompt(home, base)
    for name, value in values.items():
        text = text.replace(f"{{{name}}}", value)
    if db is not None:
        # The lead's hand-over table comes from the other agents' descriptions (cards.handovers).
        text = text.replace("{{handovers}}", cards.handovers(db, agent))
        text = cards.fill(db, text, agent)
    text = for_tools(text, tools)
    system = for_tools(packaged("system.md"), tools)
    if db is not None:
        # Names come from the cards, so renaming the lead renames it here too.
        system = cards.fill(db, system, agent)
    layers = [
        Layer(
            "System prompt",
            system.format(system_context=system_context(config), capabilities=capabilities).strip(),
        )
    ]
    # Second, and stable: it changes only when a card does, so the model server can cache it.
    team = cards.who_you_are(db, agent, skills) if db is not None else ""
    if team:
        layers.append(Layer("Who you are", team))
    layers.append(Layer("Agent prompt", text))
    if found is not None and found.kind == "yours":
        # Run as the lead, with what's different about a routine: nobody is waiting on it.
        note = agent_base(cards.ROUTINE_NOTE)
        for name, value in values.items():
            note = note.replace(f"{{{name}}}", value)
        layers.append(
            Layer("This routine", cards.fill(db, note, agent) if db is not None else note)
        )
    if found is not None and found.instructions:
        layers.append(Layer("Your instructions", found.instructions.strip()))
    if about:
        layers.append(Layer("About the person", about))
    personal = personal_prompts(home)
    if personal:
        layers.append(Layer("Personalized prompts", personal))
    if corrections:
        layers.append(Layer("What you corrected", corrections))
    if brief_wishes:
        layers.append(Layer("How they want the brief", brief_wishes))
    if mailbox:
        layers.append(Layer("What the mailbox shows", mailbox))
    if memory:
        layers.append(Layer("Memory", memory))
    return layers
