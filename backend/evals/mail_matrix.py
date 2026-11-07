"""Mail judging across models and efforts, with the cost of each, side by side.

    cd backend && uv run python evals/mail_matrix.py --runs "6.1 Sol:medium" --limit 10
    cd backend && uv run python evals/mail_matrix.py --runs "6 Luna:light,6.1 Terra:medium"

Each run gives the Mail agent its real prompt (its card, team block and skills index, with an
invented corporate persona) and the cases' invented mail, on a throwaway Home. Graded by code:
status, next action, importance, notify, tasks, follow-ups. Every run records its model, effort,
tokens, time and, when ChatGPT reports it, the share of the plan's 5-hour and weekly windows used.

It spends the person's ChatGPT allowance. Run it only when they've agreed to the spend.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import mail_eval  # noqa: E402
import scratch  # noqa: E402

from nexusai.modules.agent import gateway, mail_agent, prompts_builder, skills  # noqa: E402
from nexusai.modules.agent.gateway import Layer  # noqa: E402
from nexusai.modules.agent.providers import Message  # noqa: E402

CASES = Path(__file__).with_name("mail_cases_corp.json")
RESULTS = Path(__file__).with_name("results")


def layers_for(ctx: Any, home: Path, persona: dict[str, str]) -> list[Layer]:
    folder = home / "prompts" / "personal"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "importance.md").write_text(persona["personal"], encoding="utf-8")
    layers = prompts_builder.build_layers(
        ctx.config,
        "mail",
        about=persona["about"],
        corrections=persona["corrections"],
        mailbox=persona["mailbox"],
        db=ctx.bus.db,
        skills=skills.index(ctx, "mail"),
        scratch="your scratch folder",
    )
    now = datetime.now().astimezone().strftime("%A %d %B %Y %H:%M")
    return [*layers, Layer("This run", f"New mail arrived.\nNow: {now}")]


def task_for(case: dict[str, Any], categories: str) -> str:
    return mail_eval._case_task(case).replace(mail_eval.CATEGORIES, categories)


def run_one(
    ctx: Any, home: Path, data: dict[str, Any], cases: list[dict[str, Any]], model: str, effort: str
) -> dict[str, Any]:
    identifier, name = scratch.resolve(ctx, model)
    scratch.use_model(identifier, effort)
    layers = layers_for(ctx, home, data["persona"])
    told = mail_agent._template("mail-model")
    first = scratch.last_call(ctx)
    before = scratch.plan_usage()
    results = []
    started = time.monotonic()
    for case in cases:
        began = time.monotonic()
        try:
            done = gateway.call_model(
                ctx,
                agent="mail",
                session=None,
                layers=layers,
                messages=[Message("user", f"{task_for(case, data['categories'])}\n\n{told}")],
                tools=[mail_eval._tool()],
            )
            got = done.tool_calls[0].arguments if done.tool_calls else {"no_call": done.text}
        except Exception as error:  # noqa: BLE001 - recorded, so one failure doesn't end the run
            got = {"error": f"{type(error).__name__}: {error}"}
        missed = mail_eval._missed(case["want"], got) if "error" not in got else [got["error"]]
        results.append(
            {
                "case": case["id"],
                "passed": not missed,
                "missed": missed,
                "got": {
                    k: got.get(k)
                    for k in (
                        "status",
                        "next_action",
                        "importance",
                        "notify",
                        "category",
                        "tasks",
                        "follow_up_on",
                        "reason",
                        "error",
                        "no_call",
                    )
                },
                "seconds": round(time.monotonic() - began, 1),
            }
        )
        if not before and scratch.plan_usage():
            # ChatGPT first reports usage with its first reply, so that's the baseline, and the
            # share used misses that one call. plan_after holds the absolute figures too.
            before = scratch.plan_usage()
        mark = "ok  " if not missed else "MISS"
        print(f"  {mark} {case['id']}" + ("" if not missed else f"  >> {'; '.join(missed)}"))
    return {
        "model": name,
        "model_id": identifier,
        "effort": effort,
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "tokens": scratch.tokens_since(ctx, first),
        "seconds": round(time.monotonic() - started, 1),
        "plan_before": before,
        "plan_after": scratch.plan_usage(),
        "plan_used": scratch.used_percent(before, scratch.plan_usage()),
        "results": results,
    }


def summary(row: dict[str, Any]) -> str:
    total = row["tokens"]["input"] + row["tokens"]["output"]
    used = scratch.describe(row["plan_used"]) or "not reported"
    return (
        f"{row['passed']}/{row['cases']} as wanted, {total:,} tokens in"
        f" {row['tokens']['calls']} calls, {row['seconds']} s, plan used: {used}"
    )


def table_row(row: dict[str, Any]) -> str:
    total = row["tokens"]["input"] + row["tokens"]["output"]
    used = scratch.describe(row["plan_used"]) or "not reported"
    cells = [
        row["model"],
        row["effort"],
        f"{row['passed']}/{row['cases']}",
        f"{total:,}",
        str(row["tokens"]["calls"]),
        str(row["seconds"]),
        used,
    ]
    return "| " + " | ".join(cells) + " |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runs", required=True, help='Model:effort pairs, e.g. "6.1 Sol:medium,6 Luna:light"'
    )
    parser.add_argument("--limit", type=int, default=0, help="Only the first N cases. 0 is all.")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument(
        "--stop-percent",
        type=float,
        default=10.0,
        help="Stop before the next run if one run used more than this share of the 5-hour window.",
    )
    options = parser.parse_args()
    runs = []
    for pair in options.runs.split(","):
        model, _, effort = pair.strip().partition(":")
        effort = effort.strip().lower() or "medium"
        if effort not in scratch.EFFORTS or effort == "high":
            raise SystemExit("Agents run at light or medium. High is only for the judge.")
        runs.append((model.strip(), effort))
    data = json.loads(options.cases.read_text(encoding="utf-8"))
    cases = data["cases"][: options.limit] if options.limit else data["cases"]
    report: list[dict[str, Any]] = []
    stopped = None
    with scratch.scratch_home() as (ctx, home):
        for model, effort in runs:
            print(f"\n{model} at {effort}, {len(cases)} cases")
            row = run_one(ctx, home, data, cases, model, effort)
            report.append(row)
            used = max((v for k, v in row["plan_used"].items() if "primary" in k), default=0.0)
            print(f"  {summary(row)}")
            if used > options.stop_percent:
                stopped = f"Stopped after {model}: it used {used}% of the 5-hour window."
                print(stopped)
                break
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(UTC):%Y-%m-%d-%H%M}-mail-matrix.json"
    out.write_text(
        json.dumps(
            {"cases_file": options.cases.name, "stopped": stopped, "runs": report},
            indent=1,
            ensure_ascii=False,
        )
    )
    print("\n| Model | Effort | Passed | Tokens | Calls | Seconds | Plan used |")
    print("|---|---|---|---|---|---|---|")
    for row in report:
        print(table_row(row))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
