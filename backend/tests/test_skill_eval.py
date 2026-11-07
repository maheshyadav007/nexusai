"""The skill trigger eval, driven by a scripted model so it costs nothing to prove."""

import importlib.util
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import gateway
from nexusai.modules.agent import module as agent
from nexusai.modules.agent.providers import TextChunk, ToolCall, Usage
from test_team import TeamScript, lead, mail

EVAL = Path(__file__).parents[1] / "evals" / "skill_eval.py"
spec = importlib.util.spec_from_file_location("skill_eval", EVAL)
assert spec and spec.loader
skill_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill_eval)


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> TeamScript:
    fake = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda _: (fake, "script-model"))
    return fake


@pytest.fixture
def client(config: Config, script: TeamScript) -> Iterator[TestClient]:
    quick = replace(config, agent=replace(config.agent, triage_retry_seconds=0.1))
    with TestClient(create_app(quick), base_url="http://127.0.0.1:4100") as test:
        yield test


def test_the_cases_name_only_real_skills_and_agents() -> None:
    import json

    cases = json.loads(skill_eval.CASES.read_text())["cases"]
    shipped = {p.name for p in (Path(gateway.__file__).parent / "shipped_skills").iterdir()}
    assert {c["expect"] for c in cases if c["expect"]} <= shipped
    assert {c["agent"] for c in cases} <= {"session", "mail"}
    assert sum(1 for c in cases if c["expect"] is None) >= 4, "should-not-load cases matter too"


def test_the_runner_grades_first_choices_and_counts_all_repeats(
    client: TestClient, script: TeamScript
) -> None:
    cases = [
        {"id": "a", "agent": "session", "message": "Prep my meeting", "expect": "meeting-prep"},
        {"id": "b", "agent": "session", "message": "Thanks", "expect": None},
        {"id": "c", "agent": "mail", "message": "Why Finance?", "expect": None},
    ]
    script.say(
        lead(),
        [ToolCall("1", "load_skill", {"name": "meeting-prep"})],
        [ToolCall("2", "load_skill", {"name": "meeting-prep"})],
        [ToolCall("3", "reply", {"text": "You're welcome."})],
        [ToolCall("4", "load_skill", {"name": "drafting-replies"})],
    )
    script.say(mail(), [TextChunk("Because of the sender.")], [TextChunk("Same.")])
    report = skill_eval.run(agent.current().ctx, cases, repeat=2)
    rows = {row["id"]: row for row in report["results"]}
    assert rows["a"]["picks"] == ["meeting-prep", "meeting-prep"] and rows["a"]["pass_all"]
    # One wrong try in two fails pass^2, though it passes pass@2.
    assert rows["b"]["pass_any"] and not rows["b"]["pass_all"]
    assert rows["c"]["pass_all"]
    assert report["should_load"] == "1/1" and report["should_not_load"] == "1/2"


def test_the_runner_stops_at_its_budget(client: TestClient, script: TeamScript) -> None:
    script.say(lead(), [Usage(5000, 100), ToolCall("1", "reply", {"text": "ok"})])
    cases = [
        {"id": "a", "agent": "session", "message": "Hi", "expect": None},
        {"id": "b", "agent": "session", "message": "Hi again", "expect": None},
    ]
    report = skill_eval.run(agent.current().ctx, cases, repeat=1, budget=1000)
    assert report["cases"] == 1 and "budget" in report["stopped"]
