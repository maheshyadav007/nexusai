# ruff: noqa: E501 - SQL and report lines read better on one line each.
"""One working week for an invented engineer, end to end on the real app, graded by code.

    cd backend && uv run python evals/corp_e2e.py --run "6 Luna:medium"
    cd backend && uv run python evals/corp_e2e.py --run "6 Luna:medium" --skip-chat

It starts the app on a throwaway Home with an empty fake inbox and goes through what a new person
would, using corp_mailbox.json:
1. Onboarding: the First meeting interview, answered from a script, saving what it learned.
2. Mail: fifty emails arrive. Exact folders file PLM and Swarm mail; the Mail agent judges the rest, with
   only what onboarding saved to go by. Each judgement is checked against what's wanted, including
   whether new facts (a new director, who covers leave) were noted.
3. Chat: a few things the person asks Posty, checked on the tools it called, what it said, and
   what changed: no duplicate tasks, the right reminder date, mail filed in one call.

It spends the person's ChatGPT allowance, about as much as the team eval. Run it only when they've
agreed to the spend.
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "tests"))

import mail_eval  # noqa: E402
import scratch  # noqa: E402
import team_eval  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from fake_mail import PASSWORD, USER, make_mail, start_fake_mail  # noqa: E402
from nexusai.api.app import create_app  # noqa: E402
from nexusai.kernel.config import load_config  # noqa: E402
from nexusai.modules.agent import gateway, mail_agent  # noqa: E402
from nexusai.modules.agent import module as agent  # noqa: E402

DATA = Path(__file__).with_name("corp_mailbox.json")
RESULTS = Path(__file__).with_name("results")
ONBOARDING_SECONDS = 300
MAIL_SECONDS = 2400
CHAT_SECONDS = 300
ME = "arjun.rao@corp.example"


class Person:
    """Answers questions and approvals the way the invented person would, for one chat at a time."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.session: str | None = None
        self.approve: set[str] = set()
        self.answer: Any = lambda question: ""
        self.approvals: list[dict[str, Any]] = []
        self.asked: list[dict[str, Any]] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def _watch(self) -> None:
        while not self.stop.is_set():
            try:
                self._approvals()
                self._questions()
            except Exception:  # noqa: BLE001 - the app may be shutting down
                pass
            time.sleep(0.5)

    def _approvals(self) -> None:
        for item in self.client.post("/api/queries/approvals.list").json().get("approvals", []):
            if item["status"] != "pending" or any(d["id"] == item["id"] for d in self.approvals):
                continue
            choice = "once" if item["tool"] in self.approve else "deny"
            self.client.post(
                "/api/commands/approvals.decide", json={"id": item["id"], "choice": choice}
            )
            self.approvals.append(
                {
                    "id": item["id"],
                    "tool": item["tool"],
                    "summary": item["summary"],
                    "choice": choice,
                }
            )

    def _questions(self) -> None:
        for item in self.client.post("/api/queries/channel.list").json().get("messages", []):
            if item["kind"] != "ask" or item["status"] != "open" or item["session"] != self.session:
                continue
            text = self.answer(item["text"]) or "Use your best judgement."
            self.client.post(
                "/api/commands/channel.respond", json={"id": item["id"], "answer": text}
            )
            self.asked.append(
                {"session": item["session"], "question": item["text"], "answer": text}
            )


def _open_asks(session: str) -> bool:
    return bool(
        team_eval._db().fetch_all(
            "SELECT 1 FROM channel_messages WHERE session = ? AND kind = 'ask' AND status = 'open'",
            (session,),
        )
    )


def _settled(session: str) -> bool:
    def calm() -> bool:
        return team_eval.quiet() and not _open_asks(session)

    return calm() and (time.sleep(3) or calm())


def _tools(session: str) -> list[tuple[str, str]]:
    return [
        (row["tool"], (row["input"] or "").lower())
        for row in team_eval._db().fetch_all(
            "SELECT tool, input FROM tool_calls WHERE session = ? ORDER BY id", (session,)
        )
    ]


def _reply(client: TestClient, session: str) -> str:
    view = client.post("/api/queries/session.get", json={"id": session}).json()
    return "\n".join(
        part.get("text", "")
        for message in view["messages"]
        if message["role"] == "assistant"
        for part in message["parts"]
        if part.get("type") == "text"
    )


def _tokens(first: int) -> int:
    used = scratch.tokens_since(agent.current().ctx, first)
    return int(used["input"] + used["output"])


# Onboarding


def onboarding_answer(script: dict[str, Any]) -> Any:
    def answer(question: str) -> str:
        asked = question.lower()
        said = [a["answer"] for a in script["answers"] if any(w in asked for w in a["when"])]
        return " ".join(dict.fromkeys(said)) or script["fallback"]

    return answer


def run_onboarding(client: TestClient, person: Person, data: dict[str, Any]) -> dict[str, Any]:
    script = data["onboarding"]
    first = scratch.last_call(agent.current().ctx)
    started = time.monotonic()
    person.approve = {"save_personal_prompt", "remember"}
    person.answer = onboarding_answer(script)
    session = client.post("/api/commands/session.create", json={"agent": "interview"}).json()["id"]
    person.session = session
    finished = team_eval.wait_for(lambda: _settled(session), ONBOARDING_SECONDS)
    home = agent.current().ctx.config.home
    saved = "\n".join(
        path.read_text("utf-8") for path in sorted((home / "prompts" / "personal").glob("*.md"))
    )
    questions = [q for q in person.asked if q["session"] == session]
    missed = []
    if not finished:
        missed.append("timed out")
    if not questions:
        missed.append("asked nothing")
    if len(questions) > script["most_questions"]:
        missed.append(f"asked {len(questions)} questions, at most {script['most_questions']}")
    if not any(tool == "save_personal_prompt" for tool, _ in _tools(session)):
        missed.append("saved nothing with save_personal_prompt")
    for words in script["saved_has"]:
        if not any(word in saved.lower() for word in words):
            missed.append(f"saved notes don't mention {words}")
    return {
        "passed": not missed,
        "missed": missed,
        "questions": questions,
        "saved": saved,
        "reply": _reply(client, session),
        "tools": [tool for tool, _ in _tools(session)],
        "tokens": _tokens(first),
        "seconds": round(time.monotonic() - started, 1),
    }


# Mail


def _addressed(value: str) -> str:
    return value.replace(ME, USER)


def run_mail(
    client: TestClient, fake: Any, data: dict[str, Any], judged: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    first = scratch.last_call(agent.current().ctx)
    started = time.monotonic()
    for case in data["cases"]:
        fake.state.deliver(
            make_mail(
                subject=case["subject"],
                sender=case["from"],
                to=_addressed(case["to"]),
                cc=_addressed(case["cc"]) if case.get("cc") else None,
                body=case["body"],
            )
        )
    count = len(data["cases"])
    team_eval.wait_for(lambda: len(team_eval._threads(client)) >= count, 120)

    def done() -> bool:
        waiting = team_eval._db().fetch_all(
            "SELECT 1 FROM trigger_runs WHERE status IN ('pending', 'running') LIMIT 1"
        )
        return not waiting and team_eval.quiet() and (time.sleep(5) or team_eval.quiet())

    finished = team_eval.wait_for(done, MAIL_SECONDS)
    threads = {t["subject"]: t for t in team_eval._threads(client)}
    rows = []
    for case in data["cases"]:
        thread = threads.get(case["subject"])
        got = judged.get(thread["id"]) if thread else None
        missed = []
        if not thread:
            missed.append("never arrived")
        else:
            if case.get("rule_category") and thread.get("category") != case["rule_category"]:
                missed.append(f"filed in {thread.get('category')}, wanted {case['rule_category']}")
            # Rule-filed mail skips the agent, except what looks consequential, like a failed build.
            if "want" in case and not case.get("skip_agent"):
                missed += (
                    mail_eval._missed(case["want"], got) if got else ["the agent never judged it"]
                )
        rows.append(
            {
                "case": case["id"],
                "kind": case["kind"],
                "passed": not missed,
                "missed": missed,
                "category": thread.get("category") if thread else None,
                "judged": got is not None,
                "got": {
                    key: (got or {}).get(key)
                    for key in (
                        "status",
                        "next_action",
                        "importance",
                        "notify",
                        "tasks",
                        "memory",
                        "learned",
                        "smart_folders",
                        "question",
                        "reason",
                    )
                },
            }
        )
    kinds: dict[str, list[int]] = {}
    for row in rows:
        kinds.setdefault(row["kind"], [0, 0])
        kinds[row["kind"]][0] += row["passed"]
        kinds[row["kind"]][1] += 1
    db = team_eval._db()
    return {
        "passed": sum(r["passed"] for r in rows),
        "cases": len(rows),
        "timed_out": not finished,
        "by_kind": {kind: f"{n}/{total}" for kind, (n, total) in kinds.items()},
        "memory_proposals": [r["text"] for r in db.fetch_all("SELECT text FROM memory_proposals")],
        "results": rows,
        "tokens": _tokens(first),
        "seconds": round(time.monotonic() - started, 1),
    }


# Chat


def _work(words: list[str]) -> list[str]:
    rows = team_eval._db().fetch_all(
        "SELECT title || ' ' || notes AS text FROM tasks"
        " UNION ALL SELECT title AS text FROM reminders"
    )
    return [r["text"] for r in rows if any(w in r["text"].lower() for w in words)]


def grade_chat(step: dict[str, Any], client: TestClient, session: str, reply: str) -> list[str]:
    called = _tools(session)
    names = [tool for tool, _ in called]
    text = reply.lower()
    missed = []
    if step.get("tools_any") and not set(step["tools_any"]) & set(names):
        missed.append(f"called none of {step['tools_any']}")
    for tool in step.get("tools_all", []):
        if tool not in names:
            missed.append(f"didn't call {tool}")
    for earlier, later in step.get("before", []):
        if later in names:
            first = names.index(later)
            if not set(earlier.split("|")) & set(names[:first]):
                missed.append(f"{later} without {earlier} first")
    for group in step.get("reply_any", []):
        if not any(word in text for word in group):
            missed.append(f"reply doesn't mention any of {group}")
    for word in step.get("reply_none", []):
        if word in text:
            missed.append(f"reply mentions {word}")
    for tool, most in step.get("at_most_calls", {}).items():
        if names.count(tool) > most:
            missed.append(f"called {tool} {names.count(tool)} times, at most {most}")
    if "work_like" in step:
        spec = step["work_like"]
        found = _work(spec["words"])
        if not spec["min"] <= len(found) <= spec["max"]:
            missed.append(f"{len(found)} tasks or reminders about {spec['words']}: {found}")
    if "reminder_like" in step:
        spec = step["reminder_like"]
        rows = team_eval._db().fetch_all("SELECT title, due_at FROM reminders")
        like = [dict(r) for r in rows if any(w in r["title"].lower() for w in spec["words"])]
        if not any(str(r["due_at"]).startswith(spec["on"]) for r in like):
            missed.append(f"no reminder on {spec['on']}: {like}")
    if "notes_has" in step:
        home = agent.current().ctx.config.home
        notes = home / "memory" / "user" / "notes.md"
        noted = (notes.read_text("utf-8") if notes.exists() else "") + "\n".join(
            r["text"] for r in team_eval._db().fetch_all("SELECT text FROM memory_proposals")
        )
        for word in step["notes_has"]:
            if word not in noted.lower():
                missed.append(f"not noted: {word}")
    for category, subjects in step.get("filed", {}).items():
        for thread in team_eval._threads(client):
            if (
                any(s.lower() in thread["subject"].lower() for s in subjects)
                and thread.get("category") != category
            ):
                missed.append(f"{thread['subject']!r} is in {thread.get('category')}")
    return missed


def run_chat(client: TestClient, person: Person, step: dict[str, Any]) -> dict[str, Any]:
    first = scratch.last_call(agent.current().ctx)
    started = time.monotonic()
    person.approve = set(step.get("approve", []))
    person.answer = lambda question: step.get("answer", "")
    session = client.post("/api/commands/session.create", json={}).json()["id"]
    person.session = session

    # A question to the person holds the stream open until it's answered, so it goes behind.
    def send() -> None:
        client.post("/api/sessions/chat", json={"id": session, "text": step["message"]})

    threading.Thread(target=send, daemon=True).start()
    time.sleep(2)
    finished = team_eval.wait_for(lambda: _settled(session), CHAT_SECONDS)
    reply = _reply(client, session)
    missed = grade_chat(step, client, session, reply) + ([] if finished else ["timed out"])
    return {
        "case": step["name"],
        "passed": not missed,
        "missed": missed,
        "reply": reply,
        "tools": [tool for tool, _ in _tools(session)],
        "asked": [q for q in person.asked if q["session"] == session],
        "tokens": _tokens(first),
        "seconds": round(time.monotonic() - started, 1),
    }


# The run


def run(data: dict[str, Any], skip_chat: bool) -> dict[str, Any]:
    judged: dict[int, dict[str, Any]] = {}
    original = mail_agent._record_current

    def spy(ctx: Any, session: str, fields: dict[str, Any]) -> str:
        turn = ctx.bus.db.fetch_all(
            "SELECT target FROM agent_turns WHERE session = ? AND closed = 0 ORDER BY id DESC LIMIT 1",
            (session,),
        )
        target = json.loads(turn[0]["target"]) if turn and turn[0]["target"] else {}
        if "thread" in target:
            judged[int(target["thread"])] = dict(fields)
        return original(ctx, session, fields)

    mail_agent._record_current = spy
    fake = start_fake_mail()
    try:
        with tempfile.TemporaryDirectory(prefix="nexusai-corp-e2e-") as folder:
            os.environ["NEXUSAI_APP_DATA"] = str(Path(folder) / "app")
            os.environ["NEXUSAI_LEARN_EMAILS"] = "0"
            os.environ["NEXUSAI_ENV_FILE"] = os.devnull
            home = Path(folder) / "home"
            team_eval.prepare(home)
            config = replace(load_config(home), require_install_token=False)
            with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as client:
                setup(client, fake, data)
                person = Person(client)
                try:
                    report: dict[str, Any] = {"onboarding": run_onboarding(client, person, data)}
                    print(f"  onboarding: {line(report['onboarding'])}")
                    report["mail"] = run_mail(client, fake, data, judged)
                    print(
                        f"  mail: {report['mail']['passed']}/{report['mail']['cases']},"
                        f" {report['mail']['tokens']:,} tokens, {report['mail']['seconds']} s"
                    )
                    for kind, score in report["mail"]["by_kind"].items():
                        print(f"    {kind}: {score}")
                    for row in report["mail"]["results"]:
                        if not row["passed"]:
                            print(f"    MISS {row['case']}: {'; '.join(row['missed'])}")
                    report["chat"] = []
                    for step in [] if skip_chat else data["chat"]:
                        row = run_chat(client, person, step)
                        report["chat"].append(row)
                        mark = "ok  " if row["passed"] else "MISS"
                        print(
                            f"  {mark} chat {step['name']}: {row['tokens']:,} tokens, {row['seconds']} s"
                            + ("" if row["passed"] else f"  >> {'; '.join(row['missed'])}")
                        )
                finally:
                    person.stop.set()
                return report
    finally:
        fake.stop()
        mail_agent._record_current = original


def setup(client: TestClient, fake: Any, data: dict[str, Any]) -> None:
    """What a new person does before anything arrives: their name and folders."""
    person = data["person"]
    _ok(
        client.post(
            "/api/commands/profile.update", json={"name": person["name"], "role": person["role"]}
        )
    )
    saved = client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "work", "profile": fake.profile(), "password": PASSWORD},
    )
    if saved.status_code != 200:
        raise RuntimeError(f"Couldn't connect the invented inbox: {saved.text[:300]}")
    team_eval.wait_for(
        lambda: client.post("/api/queries/mail.status").json()["state"] == "live", 60
    )
    # Exact folders are the rules: PLM by subject, Swarm by sender, filed without the agent.
    for folder in data["folders"]:
        _ok(client.post("/api/commands/categories.save", json={**folder, "in_priority": False}))
    with team_eval._db().transaction() as tx:
        tx.execute("UPDATE agent_triggers SET enabled = 1 WHERE id = ?", (mail_agent.MAIL_TRIGGER,))


def _ok(response: Any) -> None:
    if response.status_code != 200:
        raise RuntimeError(f"Setup failed: {response.text[:300]}")


def line(part: dict[str, Any]) -> str:
    mark = "ok" if part["passed"] else "MISS " + "; ".join(part["missed"])
    return f"{mark}, {len(part['questions'])} questions, {part['tokens']:,} tokens, {part['seconds']} s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="6 Luna:medium", help='Model:effort, e.g. "6 Luna:medium"')
    parser.add_argument("--skip-chat", action="store_true", help="Stop after judging the mail.")
    options = parser.parse_args()
    model, _, effort = options.run.partition(":")
    effort = effort.strip().lower() or "medium"
    if effort not in ("light", "medium"):
        raise SystemExit("Agents run at light or medium. High is only for the judge.")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    original = gateway.resolve_provider
    try:
        with scratch.scratch_home() as (ctx, _home):
            identifier, name = scratch.resolve(ctx, model.strip())
        scratch.use_model(identifier, effort)
        before = scratch.plan_usage()
        print(f"\n{name} at {effort}")
        report = run(data, options.skip_chat)
        after = scratch.plan_usage()
    finally:
        gateway.resolve_provider = original
        gateway.EFFORT_OVERRIDE = None
    chat = report["chat"]
    tokens = (
        report["onboarding"]["tokens"] + report["mail"]["tokens"] + sum(r["tokens"] for r in chat)
    )
    summary = {
        "model": name,
        "model_id": identifier,
        "effort": effort,
        "onboarding": "passed" if report["onboarding"]["passed"] else "missed",
        "mail": f"{report['mail']['passed']}/{report['mail']['cases']}",
        "chat": f"{sum(r['passed'] for r in chat)}/{len(chat)}",
        "tokens": tokens,
        "plan_used": scratch.used_percent(before, after),
    }
    print(
        f"\n  onboarding {summary['onboarding']}, mail {summary['mail']}, chat {summary['chat']},"
        f" {tokens:,} tokens, plan used: {scratch.describe(summary['plan_used']) or 'not reported'}"
    )
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(UTC):%Y-%m-%d-%H%M}-corp-e2e.json"
    out.write_text(
        json.dumps({"summary": summary, **report}, indent=1, ensure_ascii=False, default=str)
    )
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
