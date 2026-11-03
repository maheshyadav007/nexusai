"""Assembles the prompt layers for every run, in the same order, top layer winning."""

import os
import platform
import shutil
import sys
from importlib import resources
from pathlib import Path

from nexusai.kernel.config import Config
from nexusai.modules.agent.gateway import Layer

PERSONAL_ORDER = ("about-me.md", "importance.md", "categories.md", "senders.md", "topics.md")
TOOLS_TO_REPORT = ("python3", "git", "node", "uv")


def packaged(name: str) -> str:
    return resources.files(__package__).joinpath("prompts", name).read_text("utf-8")


def system_context(config: Config) -> str:
    """Told once, in the system prompt only, so commands suit this computer."""
    shell = "PowerShell" if sys.platform == "win32" else os.environ.get("SHELL", "/bin/zsh")
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
    return "\n\n".join((folder / name).read_text("utf-8").strip() for name in names).strip()


def agent_prompt(home: Path, agent: str) -> str:
    base = packaged(f"{agent}.md")
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
    **values: str,
) -> list[Layer]:
    home = config.home
    # Only the known fields are filled in, so braces in someone's own prompt stay as written.
    text = agent_prompt(home, agent)
    for name, value in values.items():
        text = text.replace(f"{{{name}}}", value)
    layers = [
        Layer(
            "System prompt",
            packaged("system.md")
            .format(system_context=system_context(config), capabilities=capabilities)
            .strip(),
        ),
        Layer("Agent prompt", text),
    ]
    if about:
        layers.append(Layer("About the person", about))
    personal = personal_prompts(home)
    if personal:
        layers.append(Layer("Personalized prompts", personal))
    if corrections:
        layers.append(Layer("What you corrected", corrections))
    if mailbox:
        layers.append(Layer("What the mailbox shows", mailbox))
    if memory:
        layers.append(Layer("Memory", memory))
    return layers
