"""Agents, skills and prompts load from the built-in plugins exactly as they did from the old
card, prompt and skill folders (the golden file was written from the old code before the move)."""

import dataclasses
import json
from pathlib import Path

import pytest

from nexusai.modules.agent import cards, mail_agent, plugins, prompts_builder, skills

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "plugins_golden.json").read_text("utf-8"))
SOURCE = Path(plugins.__file__).parent / "builtin_plugins"


def test_every_card_is_as_it_was() -> None:
    loaded = {}
    for card in cards._files().values():
        data = dataclasses.asdict(card)
        data.pop("version")
        loaded[card.id] = json.loads(json.dumps(data))
    assert loaded == GOLDEN["cards"]
    # The team is listed in the same order as before.
    assert list(cards._files()) == sorted(GOLDEN["cards"])


def test_every_agent_prompt_is_byte_for_byte_the_same() -> None:
    # The prompt text is hashed into decision_context_version: one changed byte re-judges mail.
    for agent, text in GOLDEN["agent_prompts"].items():
        assert prompts_builder.agent_base(agent) == text, agent


def test_prompts_that_arent_an_agents_still_load_from_prompts() -> None:
    assert prompts_builder.agent_base("summary") == prompts_builder.packaged("summary.md")


def test_every_shipped_skill_is_as_it_was() -> None:
    folders = plugins.skill_folders()
    assert [folder.name for folder in folders] == [s["folder"] for s in GOLDEN["skills"].values()]
    for folder in folders:
        skill = skills.parse(skills._read_folder(folder), "built_in")
        assert json.loads(json.dumps(dataclasses.asdict(skill))) == {
            k: v for k, v in GOLDEN["skills"][skill.name].items() if k != "folder"
        }


def test_every_mail_agent_run_prompt_is_as_it_was() -> None:
    assert plugins.prompt_names() == set(GOLDEN["triggers"])
    for name, text in GOLDEN["triggers"].items():
        assert plugins.prompt(name) == text
        assert mail_agent._template(name) == text.strip()


def test_a_card_version_comes_from_its_agent_file() -> None:
    files = plugins.agent_files()
    for card in cards._files().values():
        assert card.version == files[card.id].hash


def test_built_in_plugins_follow_the_format() -> None:
    names = {plugin.name for plugin in plugins.built_in()}
    assert names == {"nexusai", "mail", "brief", "meetings"}
    assert {p.name for p in plugins.built_in() if p.required} == {"nexusai", "mail"}
    for folder in SOURCE.iterdir():
        if not folder.is_dir():
            continue
        # A root plugin.json, so packaging never has to carry a hidden folder.
        assert (folder / "plugin.json").is_file(), folder.name
        assert not any(part.startswith(".") for p in folder.rglob("*") for part in p.parts[-1:])
        manifest = json.loads((folder / "plugin.json").read_text("utf-8"))
        assert manifest["name"] == folder.name and manifest["description"]
    for agent in plugins.agent_files().values():
        # Anthropic's two required fields, and only our own fields under nexusai.
        assert agent.front["name"] == agent.name and agent.description
        assert set(agent.front) <= {"name", "description", "nexusai"}


def test_frontmatter_is_split_without_touching_the_body() -> None:
    front, body = plugins.split("---\nname: x\ndescription: y\n---\nline one\n\n---\nnot front\n")
    assert front == {"name": "x", "description": "y"}
    assert body == "line one\n\n---\nnot front\n"
    with pytest.raises(ValueError, match="frontmatter"):
        plugins.split("name: x\n")
    with pytest.raises(ValueError, match="closing"):
        plugins.split("---\nname: x\n")


def test_an_unknown_run_prompt_is_a_clear_error() -> None:
    with pytest.raises(FileNotFoundError, match="no-such"):
        plugins.prompt("no-such")
