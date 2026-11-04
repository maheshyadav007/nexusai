"""Judges made-up emails with the real model, to check the prompts do what they should.

    cd backend && uv run python evals/mail_eval.py                 all the cases
    cd backend && uv run python evals/mail_eval.py recruiter card  only cases matching a word
    cd backend && uv run python evals/mail_eval.py --thread 291    a real conversation, read only

It uses the connected model and counts towards its usage, about 3,000 tokens a case.
Usage/generation events are recorded; no mail, tasks or preferences are changed.
The cases are invented, so no real mail is kept in this file.
"""

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from nexusai.kernel import vault
from nexusai.kernel.config import load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.home import app_data_dir, default_home, read_pointer
from nexusai.kernel.module import Context
from nexusai.kernel.secrets import secret_store
from nexusai.modules.agent import gateway, knowledge, mail_agent, prompts_builder, tools
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.providers import Message, ToolSpec

CASES = Path(__file__).with_name("mail_cases.json")
CATEGORIES = "Categories that exist: Promotions, Social, Updates"


def _tool() -> ToolSpec:
    schema = tools._RecordTriage.model_json_schema()
    schema["properties"].pop("tool_call_id", None)
    schema["required"] = [name for name in schema.get("required", []) if name != "tool_call_id"]
    return ToolSpec("record_triage", "Record your judgement of the email.", schema)


def _judge(ctx: Context, layers: list[Layer], told: str, task: str) -> dict[str, Any]:
    done = gateway.call_model(
        ctx,
        agent="eval",
        session=None,
        layers=layers,
        messages=[Message("user", f"{task}\n\n{told}")],
        tools=[_tool()],
    )
    if not done.tool_calls:
        return {"no_call": done.text}
    return done.tool_calls[0].arguments


def _case_task(case: dict[str, Any]) -> str:
    lines = [f"From {case['from']}", f"To: {case['to']}"]
    if case.get("cc"):
        lines.append(f"Cc: {case['cc']}")
    mail = "\n".join(lines) + f"\n{case['body']}"
    facts = "\n".join(f"- {fact}" for fact in case["facts"])
    counted = (
        f"\n\nCounted by the app from their mailbox, so this is reliable:\n{facts}" if facts else ""
    )
    return (
        f"<untrusted>\nSubject: {case['subject']}\n\n{mail}\n</untrusted>{counted}\n\n{CATEGORIES}"
    )


def _missed(want: dict[str, Any], got: dict[str, Any]) -> list[str]:
    missed = []
    for field in ("status", "next_action", "importance", "notify"):
        actual = bool(got.get(field)) if field == "notify" else got.get(field)
        if field in want and actual not in want[field]:
            missed.append(f"{field}={got.get(field)} wanted {want[field]}")
    if want.get("tasks") and not got.get("tasks"):
        missed.append("no task")
    if want.get("follow_up") and not got.get("follow_up_on"):
        missed.append("no follow_up_on")
    if want.get("learned_empty") and got.get("learned"):
        missed.append(f"learned {got['learned']}")
    if want.get("memory_empty") and got.get("memory"):
        missed.append(f"memory {got['memory']}")
    if "category_is" in want and got.get("category") not in want["category_is"]:
        missed.append(f"category={got.get('category')} wanted {want['category_is']}")
    if got.get("category") in want.get("category_not", []):
        missed.append(f"category={got.get('category')}")
    return missed


def _layers_for_cases(ctx: Context, persona: dict[str, str], home: Path) -> list[Layer]:
    folder = home / "prompts" / "personal"
    folder.mkdir(parents=True)
    (folder / "importance.md").write_text(persona["personal"], encoding="utf-8")
    layers = prompts_builder.build_layers(
        SimpleNamespace(home=home),  # type: ignore[arg-type]
        "mail",
        about=persona["about"],
        corrections=persona["corrections"],
        mailbox=persona["mailbox"],
    )
    now = datetime.now().astimezone().strftime("%A %d %B %Y %H:%M")
    return [*layers, Layer("This run", f"New mail arrived.\nNow: {now}")]


def _run_cases(
    ctx: Context, words: list[str], cases: Path = CASES, repeat: int = 1, report: Path | None = None
) -> int:
    data = json.loads(cases.read_text(encoding="utf-8"))
    records = []
    chosen = [c for c in data["cases"] if not words or any(w in c["id"] for w in words)]
    failed = 0
    with tempfile.TemporaryDirectory() as folder:
        layers = _layers_for_cases(ctx, data["persona"], Path(folder))
        for case in [case for case in chosen for _ in range(repeat)]:
            told = mail_agent._template("mail-sent-model" if case.get("sent") else "mail-model")
            got = _judge(ctx, layers, told, _case_task(case))
            missed = _missed(case["want"], got)
            records.append(
                {
                    "case": case["id"],
                    "got": got,
                    "missed": missed,
                    "prompt_digest": hashlib.sha256(
                        "\n".join(layer.text for layer in layers).encode()
                    ).hexdigest(),
                }
            )
            failed += bool(missed)
            shown = [
                got.get(k) for k in ("status", "next_action", "importance", "notify", "category")
            ]
            print(f"{'MISS' if missed else 'ok  '} {case['id']}: {shown}")
            print(f"       why: {got.get('reason')}")
            for line in missed:
                print(f"       >> {line}")
    total = len(chosen) * repeat
    print(f"\n{total - failed} of {total} as wanted")
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "suite": str(cases),
                    "trials": repeat,
                    "total": total,
                    "failed": failed,
                    "results": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return failed


def _run_thread(ctx: Context, thread: int) -> None:
    subject, _, task = mail_agent.task_for(ctx, thread)
    layers = knowledge.layers_for(ctx, "mail", f"{subject}\n{task}", "", scratch="")
    now = datetime.now().astimezone().strftime("%A %d %B %Y %H:%M")
    layers = [*layers, Layer("This run", f"New mail arrived.\nNow: {now}")]
    got = _judge(ctx, layers, mail_agent.live_instruction(), task)
    print(json.dumps({"thread": thread, "subject": subject, **got}, ensure_ascii=False, indent=1))


def main() -> None:
    home = read_pointer(app_data_dir()) or default_home()
    config = load_config(home)
    key = vault.open_key(home, secret_store(config.secrets_test_file))
    db = Database(home / "system" / "nexusai.db", key)
    config = replace(config, database_key=key)
    ctx = Context(bus=EventBus(db, config), config=config, trace_id="eval")
    arguments = sys.argv[1:]
    if arguments[:1] == ["--thread"]:
        for thread in arguments[1:]:
            _run_thread(ctx, int(thread))
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("words", nargs="*")
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 11))
    parser.add_argument("--json", type=Path)
    options = parser.parse_args(arguments)
    sys.exit(
        1 if _run_cases(ctx, options.words, options.cases, options.repeat, options.json) else 0
    )


if __name__ == "__main__":
    main()
