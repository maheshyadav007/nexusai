"""The mail matrix runner on a scripted model, so it's proven before it spends anything."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from nexusai.modules.agent import gateway
from nexusai.modules.agent.providers import ModelRequest, ToolCall, Usage

EVALS = Path(__file__).parents[1] / "evals"


def load(name: str) -> Any:
    sys.path.insert(0, str(EVALS))
    spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Judge:
    name = "script"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def stream(self, request: ModelRequest) -> Any:
        self.requests.append(request)
        yield Usage(3000, 200)
        yield ToolCall(
            "t",
            "record_triage",
            {"status": "fyi", "next_action": "none", "importance": "low", "tasks": []},
        )


def test_the_matrix_runs_on_a_throwaway_home_and_records_cost(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NEXUSAI_APP_DATA", str(tmp_path / "app"))
    # Put back after the test, since use_model swaps these for the whole process.
    monkeypatch.setattr(gateway, "resolve_provider", gateway.resolve_provider)
    monkeypatch.setattr(gateway, "EFFORT_OVERRIDE", None)
    scratch = load("scratch")
    matrix = load("mail_matrix")
    judge = Judge()
    monkeypatch.setattr(scratch, "account_models", lambda ctx: [("gpt-6-luna", "GPT-6 Luna")])
    real_use = scratch.use_model

    def use(identifier: str, effort: str | None) -> None:
        real_use(identifier, effort)
        gateway.resolve_provider = lambda ctx: (judge, identifier)

    monkeypatch.setattr(scratch, "use_model", use)
    monkeypatch.setattr(matrix.scratch, "use_model", use)
    monkeypatch.setattr(matrix.scratch, "account_models", scratch.account_models)
    data = json.loads(matrix.CASES.read_text())
    cases = data["cases"][:3]
    with scratch.scratch_home() as (ctx, home):
        row = matrix.run_one(ctx, home, data, cases, "6 Luna", "light")
    assert row["model_id"] == "gpt-6-luna" and row["effort"] == "light"
    assert row["tokens"] == {"calls": 3, "input": 9000, "output": 600}
    # The celebration broadcast is low and needs nothing, so a judge that always says so passes it.
    passed = {r["case"]: r["passed"] for r in row["results"]}
    assert passed == {
        "hr-broadcast-hidden-deadline": False,
        "celebration-broadcast": True,
        "manager-ask-by-eod": False,
    }
    instructions = judge.requests[0].instructions
    assert "You are " in instructions and "Arjun Rao" in instructions
    assert gateway.EFFORT_OVERRIDE == "low"


def test_agents_never_run_above_medium_in_the_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = load("mail_matrix")
    monkeypatch.setattr(sys, "argv", ["mail_matrix", "--runs", "6.1 Sol:high"])
    with pytest.raises(SystemExit, match="High is only for the judge"):
        matrix.main()
