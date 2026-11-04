"""The Cockpit: what's running, how things are doing, and what just happened."""
# ruff: noqa: F811

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from test_agent_work import (  # noqa: F401
    Script,
    app_config,
    client,
    connect,
    fake,
    script,
    triaged,
    wait,
)
from test_chat_engine import chat, new_session

# More than one page of the event log holds.
LOG_PAGE_OVERFLOW = 205


def feed(client: TestClient, kind: str = "all") -> list[dict[str, str]]:
    return client.post("/api/queries/cockpit.events", json={"filter": kind}).json()["events"]


def health(client: TestClient) -> dict[str, dict[str, str]]:
    items = client.post("/api/queries/cockpit.view").json()["health"]
    return {item["id"]: item for item in items}


def test_new_mail_and_its_judgement_show_in_the_feed(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Cockpit mail"))
    triaged(client, "Cockpit mail")
    titles = wait(
        lambda: (lambda rows: rows if "Judged: Cockpit mail" in rows else None)(
            [row["title"] for row in feed(client)]
        ),
        "the feed",
    )
    assert "New mail: Cockpit mail" in titles
    assert "Mail agent started on new mail" in titles
    # The newest comes first.
    assert titles.index("Judged: Cockpit mail") < titles.index("New mail: Cockpit mail")
    assert {row["group"] for row in feed(client, "mail")} == {"mail"}
    assert {row["group"] for row in feed(client, "agents")} == {"agents"}


def test_a_failed_chat_shows_under_problems(client: TestClient, script: Script) -> None:
    from nexusai.modules.agent.providers import ModelFlagged

    session = new_session(client)
    script.replies = [[ModelFlagged("It looks sensitive.")]]
    chat(client, session, "Hello")
    problems = wait(lambda: feed(client, "problems"), "the problem")
    assert problems[0]["title"].startswith("Failed:")
    assert problems[0]["detail"] == "It looks sensitive."
    assert problems[0]["link"] == f"/agent/sessions/{session}"


def test_the_quiet_changes_stay_out_of_the_feed(client: TestClient, script: Script) -> None:
    session = new_session(client)
    client.post("/api/commands/session.rename", json={"id": session, "title": "Renamed"})
    assert not [row for row in feed(client) if "Renamed" in row["title"]]


def test_health_says_what_is_connected(client: TestClient, script: Script, fake: FakeMail) -> None:
    before = health(client)
    assert before["mail"]["state"] == "off"
    assert before["index-mail"]["state"] == "off"
    assert before["index-document"]["state"] == "off"
    connect(client, fake)
    assert health(client)["mail"]["state"] == "ok"


def test_a_session_at_work_shows_as_running(client: TestClient, script: Script) -> None:
    import threading

    from nexusai.modules.agent.providers import TextChunk

    session = new_session(client)
    script.gate = threading.Event()
    script.replies = [[TextChunk("Slow.")]]
    done: list[bool] = []
    threading.Thread(
        target=lambda: (chat(client, session, "Hello"), done.append(True)), daemon=True
    ).start()
    jobs = wait(
        lambda: [
            job
            for job in client.post("/api/queries/cockpit.view").json()["jobs"]
            if job["id"] == f"session-{session}"
        ],
        "the job",
    )
    assert jobs[0]["kind"] == "session"
    script.gate.set()
    wait(lambda: done, "the run to end")


def test_a_failed_import_isnt_running_work(client: TestClient, script: Script) -> None:
    with client.app.state.bus.db.transaction() as tx:  # type: ignore[attr-defined]
        tx.execute("INSERT INTO pst_imports (path, name, status) VALUES ('/x', 'x.pst', 'failed')")
    assert not client.post("/api/queries/cockpit.view").json()["jobs"]


def test_upcoming_runs_are_listed_and_the_hour_timer_shows_when_on(
    client: TestClient, script: Script
) -> None:
    client.post("/api/commands/schedules.save", json={"title": "Weekly", "prompt": "Go"})
    client.post("/api/commands/mailAgent.save", json={"mode": "hourly"})
    upcoming = client.post("/api/queries/cockpit.view").json()["upcoming"]
    assert {run["title"] for run in upcoming} == {
        "Weekly",
        "Mail agent, hourly",
        "Your brief",
        "Inbox review",
    }


def test_old_events_are_removed_but_never_unhandled_ones(
    client: TestClient, script: Script
) -> None:
    bus = client.app.state.bus  # type: ignore[attr-defined]
    with bus.unit_of_work() as work:
        kept = work.emit("mail.sent", {"thread_id": None}, source="test")
    wait(
        lambda: bus.db.fetch_all("SELECT 1 FROM event_cursors WHERE seq >= ?", (kept.seq,)), "seen"
    )
    # Cursor edits and deletion assertions belong to one controlled snapshot. The live
    # scheduler may prune old events, and listeners advance their cursors concurrently.
    with bus.db.serialized():
        with bus.db.transaction() as tx:
            tx.execute(
                "INSERT INTO events (id, type, version, time, source, trace_id, depth, payload)"
                " VALUES ('old', 'mail.sent', 1, '2001-01-01T00:00:00+00:00', 'test', 't', 0, '{}')"
            )
            # A listener that's still behind holds everything after its place.
            tx.execute(
                "UPDATE event_cursors SET seq = 0 WHERE listener = (SELECT MIN(listener) FROM event_cursors)"
            )
        future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        assert bus.prune(future) == 0
        with bus.db.transaction() as tx:
            tx.execute("UPDATE event_cursors SET seq = (SELECT MAX(seq) FROM events)")
        assert bus.prune("2002-01-01T00:00:00+00:00") == 1
        assert not bus.db.fetch_all("SELECT 1 FROM events WHERE id = 'old'")
        assert bus.db.fetch_all("SELECT 1 FROM events WHERE id = ?", (kept.id,))


# Home


def today(client: TestClient) -> dict[str, Any]:
    result: dict[str, Any] = client.post("/api/queries/today.view").json()
    return result


def test_home_says_what_needs_you_and_whats_due(client: TestClient, script: Script) -> None:
    assert today(client)["brief"] == "Nothing needs you right now."
    now = datetime.now().astimezone()
    client.post(
        "/api/commands/tasks.save",
        json={"title": "Budget reply", "due": now.strftime("%Y-%m-%d")},
    )
    late = (now - timedelta(days=2)).strftime("%Y-%m-%d")
    client.post("/api/commands/tasks.save", json={"title": "Vendor contract", "due": late})
    client.post(
        "/api/commands/tasks.save",
        json={"title": "Someday", "due": (now + timedelta(days=9)).strftime("%Y-%m-%d")},
    )
    client.post(
        "/api/commands/reminders.save",
        json={"title": "Call Jin", "when": now.strftime("%Y-%m-%dT23:50")},
    )
    with client.app.state.bus.db.transaction() as tx:  # type: ignore[attr-defined]
        tx.execute(
            "INSERT INTO tasks (title, status, source, proposed, created)"
            " VALUES ('Suggested', 'open', 'agent', 1, 'now')"
        )
    view = today(client)
    assert [(item["title"], item["overdue"]) for item in view["due"]][:1] == [
        ("Vendor contract", True)
    ]
    assert {item["title"] for item in view["due"]} == {
        "Vendor contract",
        "Budget reply",
        "Call Jin",
    }
    assert view["brief"] == "1 thing needs you. Vendor contract is overdue."
    # Finished suggestions aren't waiting on anyone, and Needs you doesn't list them.
    with client.app.state.bus.db.transaction() as tx:  # type: ignore[attr-defined]
        tx.execute("UPDATE tasks SET status = 'done' WHERE title = 'Suggested'")
    assert today(client)["brief"] == "Nothing needs you right now. Vendor contract is overdue."


def test_home_counts_since_you_last_looked(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    connect(client, fake)
    script.replies = []
    script.default = None
    fake.state.deliver(make_mail(subject="While away"))
    triaged(client, "While away")
    wait(lambda: today(client)["since_last_look"]["judged"] == 1, "the count")
    since = today(client)["since_last_look"]
    assert since["mail"] == 1
    assert client.post("/api/commands/today.markSeen", json={}).is_success
    after = today(client)["since_last_look"]
    assert (after["mail"], after["judged"]) == (0, 0)
    assert after["since"]


def test_quiet_conversations_say_how_long(
    client: TestClient, script: Script, fake: FakeMail
) -> None:
    from test_agent_work import triage_reply

    connect(client, fake)
    script.replies = [triage_reply(status="waiting_on_others", importance="normal")]
    long_ago = "Mon, 01 Jan 2024 09:00:00 +0000"
    fake.state.deliver(make_mail(subject="Old thread", date=long_ago))
    triaged(client, "Old thread")
    waiting = wait(lambda: today(client)["waiting"], "the thread")
    assert waiting[0]["quiet_days"] > 300


def test_the_event_log_shows_the_newest_when_there_are_many(
    client: TestClient, script: Script
) -> None:
    bus = client.app.state.bus  # type: ignore[attr-defined]
    with bus.unit_of_work() as work:
        for number in range(LOG_PAGE_OVERFLOW):
            work.emit("mail.sent", {"number": number}, source="test")
    events = client.post("/api/events/log", json={}).json()["events"]
    assert events[-1]["payload"]["number"] == events[-2]["payload"]["number"] + 1
    assert events[-1]["seq"] == bus.latest_seq()


def jobs(client: TestClient) -> dict[str, dict[str, Any]]:
    rows = client.post("/api/queries/cockpit.view").json()["jobs"]
    return {row["id"]: row for row in rows}


def test_a_pst_on_its_way_up_shows_with_its_numbers(client: TestClient, script: Script) -> None:
    started = client.post(
        "/api/commands/pst.uploadStart", json={"name": "big.pst", "size": 10, "modified": 9}
    ).json()
    client.post(f"/api/pst/upload/{started['id']}?offset=0", content=b"12345")
    row = jobs(client)[f"upload-{started['id']}"]
    assert (row["title"], row["progress"], row["total"]) == ("Sending big.pst", 5, 10)
    client.post(f"/api/pst/upload/{started['id']}?offset=5", content=b"67890")
    assert f"upload-{started['id']}" not in jobs(client)


def test_looking_for_pst_files_shows_while_it_runs(
    client: TestClient, script: Script, monkeypatch: Any
) -> None:
    from nexusai.modules.mail import pst_search

    monkeypatch.setattr(pst_search.search.status, "state", "running")
    monkeypatch.setattr(pst_search.search.status, "place", "/Users/me/Documents")
    assert jobs(client)["pst-search"]["status"] == "/Users/me/Documents"


def test_mail_download_has_numbers_while_it_comes_down(
    client: TestClient, script: Script, monkeypatch: Any
) -> None:
    from nexusai.contracts.mail import MailStatus
    from nexusai.modules.agent import module as agent_module

    downloading = MailStatus(account="t", state="backfilling", total=100, done=40)
    monkeypatch.setattr(agent_module.mail, "get_status", lambda *_: downloading)
    row = jobs(client)["mail-sync"]
    assert (row["progress"], row["total"]) == (40, 100)
