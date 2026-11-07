"""Checks each agent loads a skill when the work calls for it, and only then.

    cd backend && uv run python evals/skill_eval.py                 all the cases, once
    cd backend && uv run python evals/skill_eval.py --repeat 3      each case 3 times (pass^3)
    cd backend && uv run python evals/skill_eval.py --budget 50000  stop at 50,000 tokens

It uses the connected model and counts towards its usage, roughly 4,000 tokens a case. Only run it
when the person has agreed to the spend. Nothing in the mailbox, tasks or memory is changed.

Each case gives the agent its real prompt, with its skills index, and two tools: load_skill and
reply (go ahead without a skill). The first tool it picks is what's graded.
"""

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexusai.kernel import vault
from nexusai.kernel.config import load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.home import app_data_dir, default_home, read_pointer
from nexusai.kernel.module import Context
from nexusai.kernel.secrets import secret_store
from nexusai.modules.agent import gateway, knowledge
from nexusai.modules.agent.providers import Message, ToolSpec

CASES = Path(__file__).with_name("skill_cases.json")
RESULTS = Path(__file__).with_name("results")
TOOLS = [
    ToolSpec(
        "load_skill",
        "Load a skill from the list in your prompt when it fits the work, and follow it.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    ),
    ToolSpec(
        "reply",
        "Go ahead without a skill: answer, or start the work with your other tools.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
]


def choice(ctx: Context, agent: str, message: str) -> str | None:
    """The skill the agent loads first, or None when it goes ahead without one."""
    layers = knowledge.layers_for(ctx, agent, message, scratch="your scratch folder")
    done = gateway.call_model(
        ctx,
        agent="eval",
        session=None,
        layers=layers,
        messages=[Message("user", message)],
        tools=TOOLS,
    )
    first = done.tool_calls[0] if done.tool_calls else None
    if first is None or first.name != "load_skill":
        return None
    return str(first.arguments.get("name", "")).strip() or None


def tokens_used(ctx: Context, since: int) -> int:
    rows = ctx.bus.db.fetch_all(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS n FROM model_calls"
        " WHERE agent = 'eval' AND id > ?",
        (since,),
    )
    return int(rows[0]["n"])


def run(ctx: Context, cases: list[dict[str, Any]], repeat: int, budget: int = 0) -> dict[str, Any]:
    start = ctx.bus.db.fetch_all("SELECT COALESCE(MAX(id), 0) AS n FROM model_calls")[0]["n"]
    results = []
    stopped = None
    for case in cases:
        picks = []
        for _ in range(repeat):
            if budget and tokens_used(ctx, start) >= budget:
                stopped = f"Stopped at the budget of {budget} tokens."
                break
            picks.append(choice(ctx, case["agent"], case["message"]))
        if not picks:
            break
        passed = [pick == case["expect"] for pick in picks]
        results.append({**case, "picks": picks, "pass_all": all(passed), "pass_any": any(passed)})
        if stopped:
            break
    should = [r for r in results if r["expect"]]
    should_not = [r for r in results if not r["expect"]]
    return {
        "time": datetime.now(UTC).isoformat(),
        "repeat": repeat,
        "cases": len(results),
        "pass_all": sum(r["pass_all"] for r in results),
        "should_load": f"{sum(r['pass_all'] for r in should)}/{len(should)}",
        "should_not_load": f"{sum(r['pass_all'] for r in should_not)}/{len(should_not)}",
        "tokens": tokens_used(ctx, start),
        "stopped": stopped,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("words", nargs="*", help="Only cases whose id has one of these words.")
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 11))
    parser.add_argument(
        "--budget", type=int, default=0, help="Most tokens to spend. 0 is no limit."
    )
    options = parser.parse_args()
    home = read_pointer(app_data_dir()) or default_home()
    config = load_config(home)
    key = vault.open_key(home, secret_store(config.secrets_test_file))
    config = replace(config, database_key=key)
    ctx = Context(
        bus=EventBus(Database(home / "system" / "nexusai.db", key), config),
        config=config,
        trace_id="eval",
    )
    cases = json.loads(CASES.read_text())["cases"]
    if options.words:
        cases = [c for c in cases if any(word in c["id"] for word in options.words)]
    report = run(ctx, cases, options.repeat, options.budget)
    for row in report["results"]:
        mark = "PASS" if row["pass_all"] else "FAIL"
        print(f"{mark}  {row['id']}: wanted {row['expect']}, got {row['picks']}")
    print(
        f"Should load {report['should_load']}, should not {report['should_not_load']},"
        f" {report['tokens']} tokens." + (f" {report['stopped']}" if report["stopped"] else "")
    )
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(UTC):%Y-%m-%d-%H%M}-skills.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"Saved {out}")
    sys.exit(0 if report["pass_all"] == report["cases"] else 1)


if __name__ == "__main__":
    main()
