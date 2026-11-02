import json
import socket
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fake_mail import PASSWORD, USER, Box, FakeMail, make_mail, start_fake_mail
from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.mail.imap import DeleteRefused, ImapSession

SECONDS = 8


@pytest.fixture
def fake() -> Iterator[FakeMail]:
    server = start_fake_mail()
    yield server
    server.stop()


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
    )
    with TestClient(
        create_app(replace(config, mail=mail)), base_url="http://127.0.0.1:8765"
    ) as test:
        yield test


def wait(check: Callable[[], Any], what: str = "condition") -> Any:
    deadline = time.monotonic() + SECONDS
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def connect(client: TestClient, fake: FakeMail) -> None:
    saved = client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "test", "profile": fake.profile(), "password": PASSWORD},
    )
    assert saved.status_code == 200, saved.text
    wait(lambda: status(client)["state"] == "live", "sync to go live")


def status(client: TestClient) -> dict[str, Any]:
    return client.post("/api/queries/mail.status").json()


def threads(client: TestClient, **body: Any) -> list[dict[str, Any]]:
    return client.post("/api/queries/threads.list", json=body).json()["threads"]


def thread_with(client: TestClient, subject: str, **body: Any) -> dict[str, Any]:
    return wait(
        lambda: next((t for t in threads(client, **body) if t["subject"] == subject), None), subject
    )


def events(client: TestClient, kind: str) -> list[dict[str, Any]]:
    return [
        e for e in client.post("/api/events/log", json={}).json()["events"] if e["type"] == kind
    ]


def test_account_test_reports_each_service(client: TestClient, fake: FakeMail) -> None:
    good = client.post(
        "/api/commands/mail.accounts.test", json={"profile": fake.profile(), "password": PASSWORD}
    )
    assert good.json()["ok"] is True
    bad = client.post(
        "/api/commands/mail.accounts.test", json={"profile": fake.profile(), "password": "wrong"}
    ).json()
    assert bad["ok"] is False
    assert all("refused" in result["message"] for result in bad["results"])


def test_smtp_never_looks_up_this_computers_name(
    client: TestClient, fake: FakeMail, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_: Any) -> str:
        raise AssertionError("getfqdn is slow on some networks, and shares the computer's name")

    monkeypatch.setattr(socket, "getfqdn", fail)
    result = client.post(
        "/api/commands/mail.accounts.test", json={"profile": fake.profile(), "password": PASSWORD}
    )
    assert result.json()["ok"] is True


def test_plain_connections_only_to_this_computer(client: TestClient, fake: FakeMail) -> None:
    profile = fake.profile()
    profile["imap"]["host"] = "mail.example.com"
    refused = client.post(
        "/api/commands/mail.accounts.save", json={"name": "x", "profile": profile, "password": "p"}
    )
    assert refused.status_code == 422
    assert "encrypted" in refused.json()["message"]


def test_the_account_is_saved_encrypted_and_the_password_never_comes_back(
    client: TestClient, fake: FakeMail, config: Config
) -> None:
    connect(client, fake)
    saved = (config.home / "system" / "mail-accounts.enc").read_text()
    assert PASSWORD not in saved
    assert USER not in saved
    assert "127.0.0.1" not in saved
    assert not (config.home / "system" / "mail-accounts.json").exists()
    assert client.post("/api/queries/mail.accounts").json()["accounts"][0]["has_password"] is True
    assert PASSWORD not in client.post("/api/queries/mail.accounts").text


def test_wrong_password_stops_and_says_so(client: TestClient, fake: FakeMail) -> None:
    client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "t", "profile": fake.profile(), "password": "wrong"},
    )
    wait(lambda: status(client)["state"] == "failed", "failure")
    assert "refused" in status(client)["message"]
    logins = fake.state.logins
    time.sleep(0.3)
    assert fake.state.logins == logins


def test_mail_after_an_empty_first_sync_counts_as_new(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    assert status(client)["messages"] == 0
    fake.state.deliver(make_mail(subject="First ever"))
    thread_with(client, "First ever")
    assert len(events(client, "mail.needsTriage")) == 1


def test_syncs_existing_mail_without_triage(client: TestClient, fake: FakeMail) -> None:
    fake.state.deliver(make_mail(subject="Old mail"))
    connect(client, fake)
    assert thread_with(client, "Old mail")["unread_count"] == 1
    assert events(client, "mail.needsTriage") == []
    assert events(client, "mail.received") == []


def test_new_mail_arrives_live_and_asks_for_triage(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Fresh"))
    thread = thread_with(client, "Fresh")
    assert events(client, "mail.received")[0]["payload"]["thread_id"] == thread["id"]
    triage = events(client, "mail.needsTriage")
    assert triage[0]["payload"]["thread_id"] == thread["id"]
    assert "Fresh" not in json.dumps(events(client, "mail.received"))


def test_rule_matched_mail_skips_triage_and_says_why(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Build passed", sender="no-reply@ci.example"))
    thread = thread_with(client, "Build passed")
    assert thread["category"] == "Updates"
    assert thread["why"] == "Matched the rule “Sent from a no-reply address”"
    assert events(client, "mail.needsTriage") == []


def test_user_rule_marks_read_categorizes_and_notifies(client: TestClient, fake: FakeMail) -> None:
    rule = {
        "name": "Audit",
        "conditions": [{"field": "subject", "value": "audit"}],
        "actions": {"category": "Audit", "mark_read": True, "skip_agent": True, "notify": True},
    }
    assert client.post("/api/commands/rules.save", json={"rules": [rule]}).status_code == 200
    assert client.post("/api/queries/rules.get").json()["rules"][0]["name"] == "Audit"
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Audit findings"))
    thread = thread_with(client, "Audit findings")
    assert thread["category"] == "Audit"
    wait(
        lambda: "\\Seen" in fake.state.boxes["INBOX"].mails[0].flags,
        "mark-read to reach the server",
    )
    assert thread_with(client, "Audit findings")["unread_count"] == 0
    notices = wait(
        lambda: client.post("/api/queries/notifications.list", json={}).json()["items"], "notice"
    )
    assert notices[0]["link"] == f"/mail/thread/{thread['id']}"


def test_large_mailbox_syncs_newest_first_then_backfills(
    client: TestClient, fake: FakeMail, config: Config
) -> None:
    for number in range(450):
        fake.state.deliver(
            make_mail(
                subject=f"Mail {number}",
                date=f"Mon, 5 Jan 2026 10:{number % 60:02d}:00 +0000",
                sender="a@x.com",
            )
        )
    connect(client, fake)
    assert wait(lambda: status(client)["messages"] == 450, "backfill")
    page = client.post("/api/queries/threads.list", json={"limit": 100}).json()
    assert len(page["threads"]) == 100 and page["next_before"]
    next_page = client.post(
        "/api/queries/threads.list", json={"limit": 100, "before": page["next_before"]}
    ).json()
    assert not {t["id"] for t in page["threads"]} & {t["id"] for t in next_page["threads"]}


def test_new_mail_isnt_kept_waiting_by_backfill(client: TestClient, fake: FakeMail) -> None:
    for number in range(1000):
        fake.state.deliver(
            make_mail(
                subject=f"Old {number}", sender="a@x.com", date="Mon, 5 Jan 2026 10:00:00 +0000"
            )
        )
    client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "t", "profile": fake.profile(), "password": PASSWORD},
    )
    wait(lambda: status(client)["messages"] >= 200, "first batch")
    fake.state.deliver(make_mail(subject="Urgent during backfill"))
    assert thread_with(client, "Urgent during backfill")
    assert status(client)["messages"] < 1001


def test_sync_resumes_after_restart_without_repeats(config: Config, fake: FakeMail) -> None:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
    )
    app_config = replace(config, mail=mail)
    fake.state.deliver(make_mail(subject="Before restart"))
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as first:
        connect(first, fake)
        thread_with(first, "Before restart")
    fake.state.deliver(make_mail(subject="While closed"))
    with TestClient(create_app(app_config), base_url="http://127.0.0.1:8765") as second:
        thread_with(second, "While closed")
        assert status(second)["messages"] == 2
        assert len(threads(second)) == 2


def test_reconnects_when_the_connection_drops(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    logins = fake.state.logins
    for idler, _ in list(fake.state.idlers):
        idler.connection.shutdown(socket.SHUT_RDWR)
    wait(lambda: fake.state.logins > logins, "reconnect")
    fake.state.deliver(make_mail(subject="After reconnect"))
    assert thread_with(client, "After reconnect")


def test_replies_join_by_references_and_out_of_order_merges(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Plan", message_id="<a@x>"))
    thread_with(client, "Plan")
    fake.state.deliver(
        make_mail(
            subject="Re: Plan",
            message_id="<b@x>",
            in_reply_to="<a@x>",
            references="<a@x>",
            sender="Sam <sam@x.com>",
        )
    )
    wait(lambda: threads(client)[0]["message_count"] == 2, "reply to join")
    assert len(threads(client)) == 1

    fake.state.deliver(
        make_mail(
            subject="Later", message_id="<z@x>", in_reply_to="<y@x>", references="<x@x> <y@x>"
        )
    )
    thread_with(client, "Later")
    fake.state.deliver(make_mail(subject="Earlier", message_id="<x@x>"))
    wait(lambda: len(threads(client)) == 2, "out-of-order parent to merge")


def test_outlook_thread_index_joins_without_references(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    root = "AQHZ" + "B" * 26
    fake.state.deliver(make_mail(subject="Budget", headers={"Thread-Index": root}))
    thread_with(client, "Budget")
    fake.state.deliver(make_mail(subject="RE: Budget", headers={"Thread-Index": root + "CCCCCC"}))
    wait(lambda: threads(client)[0]["message_count"] == 2, "thread index join")


def test_subject_fallback_needs_a_reply_prefix_and_shared_people(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Status", sender="a@x.com"))
    thread_with(client, "Status")
    fake.state.deliver(make_mail(subject="Status", sender="b@x.com", to="c@x.com"))
    wait(lambda: len(threads(client)) == 2, "unrelated mail stays apart")
    fake.state.deliver(make_mail(subject="Re: Status", sender="a@x.com", to=USER))
    wait(lambda: any(t["message_count"] == 2 for t in threads(client)), "reply by subject")


def test_thread_view_collapses_duplicates_and_marks_people_changes(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    first = make_mail(
        subject="Team",
        message_id="<t1@x>",
        to=USER,
        cc="old@x.com",
        date="Mon, 5 Jan 2026 10:00:00 +0000",
    )
    fake.state.deliver(first)
    fake.state.deliver(first, box="Sent")
    fake.state.deliver(
        make_mail(
            subject="Re: Team",
            message_id="<t2@x>",
            in_reply_to="<t1@x>",
            references="<t1@x>",
            to=USER,
            cc="new@x.com",
            date="Mon, 5 Jan 2026 11:00:00 +0000",
        )
    )
    thread = wait(
        lambda: next((t for t in threads(client) if t["message_count"] == 2), None), "both"
    )
    view = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()
    assert [m["subject"] for m in view["messages"]] == ["Team", "Re: Team"]
    assert view["messages"][1]["added"] == ["new@x.com"]
    assert view["messages"][1]["dropped"] == ["old@x.com"]


def test_safe_html_and_signature_images_in_thread_view(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    raw = make_mail(
        subject="Rich",
        html='<p>Hi</p><script>bad()</script><img src="https://evil/x.png">',
        attachments=[
            ("r.pdf", "application/pdf", b"%PDF-1"),
            ("v.exe", "application/octet-stream", b"MZ"),
        ],
    )
    fake.state.deliver(raw)
    thread = thread_with(client, "Rich")
    assert thread["has_attachments"] is True
    message = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][
        0
    ]
    assert "<script" not in message["html"]
    assert ' src="https://evil' not in message["html"]
    assert {a["filename"]: a["kind"] for a in message["attachments"]} == {
        "r.pdf": "attachment",
        "v.exe": "risky",
    }


def test_attachments_download_safely_and_risky_ones_dont(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Files",
            attachments=[
                ("r.pdf", "application/pdf", b"%PDF-1"),
                ("v.exe", "application/octet-stream", b"MZ"),
            ],
        )
    )
    thread = thread_with(client, "Files")
    message = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][
        0
    ]
    by_name = {a["filename"]: a["index"] for a in message["attachments"]}
    good = client.get(f"/api/mail/attachment/{message['id']}/{by_name['r.pdf']}")
    assert good.content == b"%PDF-1"
    assert good.headers["content-type"] == "application/octet-stream"
    assert good.headers["content-disposition"].startswith("attachment")
    assert good.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/mail/attachment/{message['id']}/{by_name['v.exe']}").status_code == 403
    assert client.get(f"/api/mail/attachment/{message['id']}/99").status_code == 404


def test_read_and_flag_sync_both_ways(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    uid = fake.state.deliver(make_mail(subject="Two way"))
    thread = thread_with(client, "Two way")
    box = fake.state.boxes["INBOX"]
    client.post("/api/commands/thread.setRead", json={"id": thread["id"], "read": True})
    assert thread_with(client, "Two way")["unread_count"] == 0
    wait(lambda: "\\Seen" in box.mails[0].flags, "read to reach the server")
    client.post("/api/commands/thread.setFlag", json={"id": thread["id"], "flagged": True})
    wait(lambda: "\\Flagged" in box.mails[0].flags, "flag to reach the server")
    assert thread_with(client, "Two way")["flagged"] is True

    fake.state.set_flags(uid, set())
    wait(lambda: thread_with(client, "Two way")["unread_count"] == 1, "server change to arrive")
    assert thread_with(client, "Two way")["flagged"] is False


def test_moving_and_deleting_reach_the_server(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Archive me"))
    thread = thread_with(client, "Archive me")
    client.post("/api/commands/thread.move", json={"id": thread["id"], "to": "archive"})
    wait(
        lambda: not any(t["subject"] == "Archive me" for t in threads(client)), "to leave the inbox"
    )
    wait(lambda: len(fake.state.boxes["Archive"].mails) == 1, "move on server")
    assert fake.state.boxes["INBOX"].mails == []


def test_removed_on_the_server_disappears_here(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    uid = fake.state.deliver(make_mail(subject="Gone soon"))
    thread_with(client, "Gone soon")
    fake.state.remove(uid)
    wait(lambda: not threads(client), "removal")
    assert status(client)["messages"] == 0


def test_changes_made_offline_are_kept_and_sent_later(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Offline"))
    thread = thread_with(client, "Offline")
    client.post(
        "/api/commands/mail.accounts.save",
        json={
            "name": "test",
            "profile": {
                **fake.profile(),
                "imap": {"host": "127.0.0.1", "port": 1, "secure": False},
            },
        },
    )
    client.post("/api/commands/thread.setRead", json={"id": thread["id"], "read": True})
    assert fake.state.boxes["INBOX"].mails[0].flags == set()
    client.post(
        "/api/commands/mail.accounts.save", json={"name": "test", "profile": fake.profile()}
    )
    wait(lambda: "\\Seen" in fake.state.boxes["INBOX"].mails[0].flags, "queued change to send")


def test_uidvalidity_change_rebuilds_the_folder(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Renumbered"))
    thread_with(client, "Renumbered")
    fake.state.boxes["INBOX"].validity = 999
    fake.state.deliver(make_mail(subject="Trigger"))
    thread_with(client, "Trigger")
    assert len(threads(client)) == 2
    assert status(client)["messages"] == 2


def test_status_and_category_are_kept_and_user_choice_wins(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Kept", message_id="<k1@x>"))
    thread = thread_with(client, "Kept")
    client.post(
        "/api/commands/thread.setStatus", json={"id": thread["id"], "status": "waiting_on_others"}
    )
    client.post(
        "/api/commands/thread.setCategory", json={"id": thread["id"], "category": "Personal"}
    )
    fake.state.deliver(
        make_mail(
            subject="Re: Kept", message_id="<k2@x>", in_reply_to="<k1@x>", sender="no-reply@x.com"
        )
    )
    wait(lambda: threads(client)[0]["message_count"] == 2, "reply")
    current = threads(client)[0]
    assert current["status"] == "waiting_on_others"
    assert current["category"] == "Personal" and current["category_source"] == "user"
    filtered = client.post("/api/queries/threads.list", json={"category": "Personal"}).json()
    assert len(filtered["threads"]) == 1 and filtered["categories"] == ["Personal"]


def test_reply_draft_keeps_the_conversation_and_warns_about_dropped_people(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(subject="Q", message_id="<q@x>", to=f"{USER}, sam@x.com", cc="lee@x.com")
    )
    thread = thread_with(client, "Q")
    message = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][
        0
    ]
    everyone = client.post(
        "/api/queries/mail.replyDraft", json={"message_id": message["id"]}
    ).json()
    assert [r["address"] for r in everyone["draft"]["to"]] == ["priya@example.com"]
    assert [r["address"] for r in everyone["draft"]["cc"]] == ["sam@x.com", "lee@x.com"]
    assert everyone["draft"]["subject"] == "Re: Q"
    assert everyone["dropped"] == []
    only = client.post(
        "/api/queries/mail.replyDraft", json={"message_id": message["id"], "reply_all": False}
    ).json()
    assert only["draft"]["cc"] == []
    assert sorted(only["dropped"]) == ["lee@x.com", "sam@x.com"]


def test_sending_reaches_smtp_threads_correctly_and_files_in_sent(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Ask", message_id="<ask@x>"))
    thread = thread_with(client, "Ask")
    message = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][
        0
    ]
    draft = client.post("/api/queries/mail.replyDraft", json={"message_id": message["id"]}).json()[
        "draft"
    ]
    draft["body"] = "Done."
    draft["bcc"] = [{"address": "hidden@x.com"}]
    assert client.post("/api/commands/mail.send", json={"draft": draft}).status_code == 200
    sent = fake.sent[0]
    assert set(sent["to"]) == {"priya@example.com", "hidden@x.com"}
    raw = sent["raw"].decode()
    assert "In-Reply-To: <ask@x>" in raw
    assert "hidden@x.com" not in raw
    wait(lambda: threads(client)[0]["message_count"] == 2, "sent copy to join the thread")
    assert any(t["subject"] == "Ask" for t in threads(client, folder="sent"))


def test_failed_send_keeps_the_draft_and_explains(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    saved = client.post(
        "/api/commands/drafts.save", json={"subject": "Keep me", "to": [{"address": "a@x.com"}]}
    ).json()
    profile = {**fake.profile(), "smtp": {"host": "127.0.0.1", "port": 1, "secure": False}}
    client.post("/api/commands/mail.accounts.save", json={"name": "test", "profile": profile})
    refused = client.post("/api/commands/mail.send", json={"draft": saved})
    assert refused.status_code == 502
    assert "saved" in refused.json()["message"]
    assert client.post("/api/queries/drafts.list").json()["drafts"][0]["subject"] == "Keep me"


def test_drafts_keep_one_copy_on_the_server(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    client.post("/api/commands/mail.sync.neverDelete", json={"value": False})
    first = client.post("/api/commands/drafts.save", json={"subject": "V1"}).json()
    wait(lambda: len(fake.state.boxes["Drafts"].mails) == 1, "first copy")
    client.post("/api/commands/drafts.save", json={**first, "subject": "V2"})
    wait(
        lambda: (
            b"V2" in fake.state.boxes["Drafts"].mails[0].raw
            if fake.state.boxes["Drafts"].mails
            else False
        ),
        "second copy",
    )
    assert len(fake.state.boxes["Drafts"].mails) == 1
    # Our own copy doesn't come back as a mail thread.
    time.sleep(0.2)
    assert threads(client, folder="drafts") == []
    client.post("/api/commands/drafts.remove", json={"id": first["id"]})
    wait(lambda: not fake.state.boxes["Drafts"].mails, "draft removal on server")
    assert client.post("/api/queries/drafts.list").json()["drafts"] == []


def test_search_finds_one_hit_per_thread_with_filters(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Supplier contract", body="The renewal is due in March.", message_id="<s1@x>"
        )
    )
    fake.state.deliver(
        make_mail(
            subject="Re: Supplier contract",
            body="Noted.\n\nOn Mon, Priya wrote:\n> The renewal is due in March.",
            message_id="<s2@x>",
            in_reply_to="<s1@x>",
            sender="sam@x.com",
        )
    )
    fake.state.deliver(
        make_mail(subject="Lunch", body="Renewal of our lunch tradition.", sender="lee@x.com")
    )
    wait(lambda: status(client)["messages"] == 3, "all mail")

    def run(**body: Any) -> list[dict[str, Any]]:
        return client.post("/api/queries/search.run", json=body).json()["hits"]

    hits = run(query="march")
    assert len(hits) == 1 and "March" in hits[0]["excerpt"]
    assert len(run(query="renewal")) == 2
    assert [h["thread"]["subject"] for h in run(query="renewal", sender="lee")] == ["Lunch"]
    assert run(query="renewal", has_attachment=True) == []
    assert run(query='"; DROP TABLE messages; --') == []
    assert len(run(sender="lee")) == 1
    assert run(query="renewal", date_from="2999-01-01") == []


def test_nothing_works_without_an_account(client: TestClient) -> None:
    assert status(client)["state"] == "off"
    assert threads(client) == []
    assert (
        client.post("/api/commands/mail.send", json={"draft": {"subject": "x"}}).json()["code"]
        == "mail.no_account"
    )


def test_mail_content_never_reaches_logs(
    client: TestClient, fake: FakeMail, config: Config
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Secret merger", body="Project bluebird details"))
    thread_with(client, "Secret merger")
    logged = "".join(p.read_text() for p in (config.home / "system" / "logs").glob("*.jsonl"))
    assert "bluebird" not in logged and "Secret merger" not in logged and PASSWORD not in logged


def test_send_checks_warn_block_and_can_be_turned_off(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Internal",
            sender=f"boss@{USER.rsplit('@')[1]}",
            message_id="<i@x>",
            date="Mon, 5 Jan 2026 10:00:00 +0000",
        )
    )
    thread = thread_with(client, "Internal")
    draft = {
        "thread_id": thread["id"],
        "to": [{"address": "outsider@other.org"}],
        "subject": "Re: Internal",
        "body": "See the attached file.",
    }

    def check(**extra: Any) -> dict[str, Any]:
        return client.post("/api/queries/mail.checkSend", json={"draft": draft, **extra}).json()

    found = {p["check"]: p for p in check(written_after="2020-01-01")["problems"]}
    assert set(found) == {"external_recipient", "missing_attachment", "newer_reply"}
    assert all(p["level"] == "warn" for p in found.values())
    assert "outsider@other.org" in found["external_recipient"]["message"]
    assert check(written_after="2099-01-01")["undo_seconds"] == 5
    assert client.post("/api/commands/mail.send", json={"draft": draft}).status_code == 200

    client.post(
        "/api/commands/sendChecks.save",
        json={
            "external_recipient": "block",
            "missing_attachment": "off",
            "newer_reply": "off",
            "undo_seconds": 0,
        },
    )
    assert [p["check"] for p in check()["problems"]] == ["external_recipient"]
    refused = client.post("/api/commands/mail.send", json={"draft": draft})
    assert refused.status_code == 422 and refused.json()["code"] == "mail.send_blocked"
    assert len(fake.sent) == 1


def pipeline(client: TestClient) -> dict[str, Any]:
    rows = client.post("/api/queries/pipelines.list").json()["pipelines"]
    return next(row for row in rows if row["id"] == "mail-sync")


def fill(fake: FakeMail, count: int, box: str = "INBOX") -> None:
    for number in range(count):
        fake.state.deliver(make_mail(subject=f"{box} {number}"), box=box)


def save(client: TestClient, fake: FakeMail, **body: Any) -> None:
    saved = client.post(
        "/api/commands/mail.accounts.save",
        json={"name": "test", "profile": fake.profile(), "password": PASSWORD, **body},
    )
    assert saved.status_code == 200, saved.text


def test_the_connection_test_counts_what_is_on_the_server(
    client: TestClient, fake: FakeMail
) -> None:
    fill(fake, 3)
    fill(fake, 2, "Sent")
    result = client.post(
        "/api/commands/mail.accounts.test", json={"profile": fake.profile(), "password": PASSWORD}
    ).json()
    assert {row["role"]: row["messages"] for row in result["counts"]}["inbox"] == 3
    assert {row["role"]: row["messages"] for row in result["counts"]}["sent"] == 2
    assert result["total"] == 5
    assert result["suggested_pull"] == 5


def test_only_the_newest_come_down_and_get_more_carries_on(
    client: TestClient, fake: FakeMail
) -> None:
    fill(fake, 12)
    save(client, fake, pull_limit=5)
    wait(lambda: status(client)["state"] == "live", "sync to go live")
    assert status(client)["pulled"] == 5
    assert status(client)["server_total"] == 12
    assert status(client)["history_finished"] is True
    subjects = {row["subject"] for row in threads(client)}
    assert subjects == {f"INBOX {number}" for number in range(7, 12)}
    finished = events(client, "mail.historyFinished")
    assert [row["payload"]["pulled"] for row in finished] == [5]

    # New mail always comes, whatever's left of the budget.
    fake.state.deliver(make_mail(subject="Just arrived"))
    thread_with(client, "Just arrived")
    assert events(client, "mail.received")

    client.post("/api/commands/mail.history.more", json={"count": 3})
    wait(lambda: status(client)["pulled"] == 9, "exactly three more")
    wait(lambda: status(client)["history_finished"], "that to finish")
    client.post("/api/commands/mail.history.more", json={})
    wait(lambda: status(client)["pulled"] == 13, "the rest to come down")
    # None of that history looked like new mail, so no agent ran on it.
    assert len(events(client, "mail.received")) == 1


def test_stop_ends_history_but_new_mail_keeps_coming(client: TestClient, fake: FakeMail) -> None:
    fill(fake, 3)
    connect(client, fake)
    fill(fake, 2, "Sent")
    stopped = client.post("/api/commands/pipelines.stop", json={"id": "mail-sync"})
    assert stopped.status_code == 200, stopped.text
    wait(lambda: status(client)["history_finished"], "history to finish")
    assert status(client)["state"] == "live"
    fake.state.deliver(make_mail(subject="Still arriving"))
    thread_with(client, "Still arriving")
    facts = {fact["label"]: fact["value"] for fact in pipeline(client)["facts"]}
    assert facts["Older mail"] == "Finished"


def test_a_budget_is_only_used_by_mail_new_to_this_computer(
    client: TestClient, fake: FakeMail
) -> None:
    for number in range(4):
        raw = make_mail(subject=f"Filed {number}")
        fake.state.deliver(raw)
        fake.state.deliver(raw, "Archive")
    save(client, fake, pull_limit=4)
    wait(lambda: status(client)["state"] == "live", "sync to go live")
    assert status(client)["pulled"] == 4
    assert fake.state.fetched_bodies == 4


def test_stopping_and_pausing_stay_as_they_were_after_a_restart(
    config: Config, fake: FakeMail
) -> None:
    mail = replace(
        config.mail, connect_timeout_seconds=3, reconnect_min_seconds=0.1, check_every_seconds=1
    )
    settings = replace(config, mail=mail)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as first:
        connect(first, fake)
        first.post("/api/commands/mail.history.stop", json={})
        first.post("/api/commands/pipelines.pause", json={"id": "mail-sync", "paused": True})
    logins = fake.state.logins
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8765") as second:
        assert status(second)["state"] == "paused"
        assert status(second)["history_budget"] == 0
        assert fake.state.logins == logins
        # Connecting the account again is asking for mail, so that starts it.
        connect(second, fake)
        assert status(second)["history_budget"] == 0


def test_stopping_holds_new_mail_until_resumed(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    stopped = client.post("/api/commands/pipelines.pause", json={"id": "mail-sync", "paused": True})
    assert stopped.status_code == 200, stopped.text
    assert status(client)["state"] == "paused"
    assert pipeline(client)["state"] == "stopped"

    fake.state.deliver(make_mail(subject="While stopped"))
    time.sleep(1.5)
    assert not [row for row in threads(client) if row["subject"] == "While stopped"]

    client.post("/api/commands/pipelines.pause", json={"id": "mail-sync", "paused": False})
    thread_with(client, "While stopped")
    wait(lambda: status(client)["state"] == "live", "sync to go live")


def test_each_check_says_what_it_found_and_pulled(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    first = wait(lambda: pipeline(client)["last_run"], "a first check")
    assert pipeline(client)["next_run"]
    assert "Every second" not in pipeline(client)["cadence"]

    fake.state.deliver(make_mail(subject="One"))
    fake.state.deliver(make_mail(subject="Two"))
    wait(lambda: events(client, "mail.pulled"), "the check to report")
    found = sum(row["payload"]["found"] for row in events(client, "mail.pulled"))
    pulled = sum(row["payload"]["pulled"] for row in events(client, "mail.pulled"))
    assert (found, pulled) == (2, 2)
    wait(lambda: pipeline(client)["last_run"] != first, "a later check")
    facts = {fact["label"]: fact["value"] for fact in pipeline(client)["facts"]}
    assert facts["On the server"] == "2"
    assert facts["On this computer"] == "2"
    assert "pulled" in facts["Last new mail"]

    # A check that finds nothing says nothing, so the log isn't filled once a minute.
    quiet = len(events(client, "mail.pulled"))
    time.sleep(1.5)
    assert len(events(client, "mail.pulled")) == quiet


def test_run_now_checks_straight_away(client: TestClient, fake: FakeMail) -> None:
    connect(client, fake)
    done = client.post("/api/commands/pipelines.run", json={"id": "mail-sync"})
    assert done.status_code == 200, done.text
    assert client.post("/api/commands/pipelines.run", json={"id": "nope"}).status_code == 404


def test_with_no_account_the_mail_schedule_says_so(client: TestClient) -> None:
    row = pipeline(client)
    assert row["available"] is False
    assert row["state"] == "stopped"
    refused = client.post("/api/commands/pipelines.pause", json={"id": "mail-sync", "paused": True})
    assert refused.status_code == 409


def folders(client: TestClient) -> dict[str, dict[str, Any]]:
    rows = client.post("/api/queries/mail.folders").json()["folders"]
    return {row["name"]: row for row in rows}


def in_location(client: TestClient, name: str) -> list[str]:
    return [row["subject"] for row in threads(client, location=name)]


def add_box(fake: FakeMail, name: str, attrs: str = "") -> None:
    fake.state.boxes[name] = Box(attrs)


def test_every_folder_syncs_and_a_new_one_appears_by_itself(
    client: TestClient, fake: FakeMail
) -> None:
    add_box(fake, "Projects/Alpha")
    fake.state.deliver(make_mail(subject="Alpha plan"), "Projects/Alpha")
    connect(client, fake)
    found = folders(client)
    assert {"INBOX", "Sent", "Drafts", "Trash", "Archive", "Projects/Alpha"} <= set(found)
    assert found["Projects/Alpha"]["label"] == "Alpha"
    assert found["Projects/Alpha"]["on_server"] == 1
    assert in_location(client, "Projects/Alpha") == ["Alpha plan"]

    add_box(fake, "Later")
    fake.state.deliver(make_mail(subject="In a new folder"), "Later")
    wait(lambda: "In a new folder" in in_location(client, "Later"), "the new folder to sync")


def test_one_email_in_three_folders_is_one_email(client: TestClient, fake: FakeMail) -> None:
    add_box(fake, "Work")
    add_box(fake, "Urgent")
    raw = make_mail(subject="Everywhere", message_id="<everywhere@example.com>")
    for box in ("INBOX", "Work", "Urgent"):
        fake.state.deliver(raw, box)
    connect(client, fake)
    assert fake.state.fetched_bodies == 1
    assert status(client)["pulled"] == 1
    for box in ("INBOX", "Work", "Urgent"):
        assert in_location(client, box) == ["Everywhere"]
    thread = thread_with(client, "Everywhere", folder="inbox")
    view = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()
    assert len(view["messages"]) == 1
    assert {row["name"] for row in view["messages"][0]["folders"]} == {"INBOX", "Work", "Urgent"}
    assert folders(client)["Work"]["unread"] == 1

    # Reading it here reads it in every folder on the server too.
    client.post("/api/commands/thread.setRead", json={"id": thread["id"], "read": True})
    assert folders(client)["Urgent"]["unread"] == 0
    wait(
        lambda: all(
            "\\Seen" in fake.state.boxes[box].mails[0].flags for box in ("INBOX", "Work", "Urgent")
        ),
        "every copy to be read",
    )
    hits = client.post("/api/queries/search.run", json={"query": "Everywhere"}).json()["hits"]
    assert len(hits) == 1


def test_a_copy_arriving_later_needs_no_second_download(client: TestClient, fake: FakeMail) -> None:
    add_box(fake, "Work")
    connect(client, fake)
    raw = make_mail(subject="Filed later")
    fake.state.deliver(raw)
    thread_with(client, "Filed later")
    downloads = fake.state.fetched_bodies
    fake.state.deliver(raw, "Work")
    wait(lambda: in_location(client, "Work") == ["Filed later"], "the copy to be noticed")
    assert fake.state.fetched_bodies == downloads
    # Only the first arrival counts as new mail, so one email starts the agent once.
    assert len(events(client, "mail.received")) == 1


def test_removing_a_copy_on_the_server_keeps_the_others(client: TestClient, fake: FakeMail) -> None:
    add_box(fake, "Work")
    raw = make_mail(subject="Two places")
    uid = fake.state.deliver(raw)
    fake.state.deliver(raw, "Work")
    connect(client, fake)
    fake.state.remove(uid)
    wait(lambda: in_location(client, "INBOX") == [], "it to leave the inbox")
    assert in_location(client, "Work") == ["Two places"]


def test_adding_to_a_folder_copies_on_the_server(client: TestClient, fake: FakeMail) -> None:
    add_box(fake, "Work")
    fake.state.deliver(make_mail(subject="File me"))
    connect(client, fake)
    thread = thread_with(client, "File me")
    client.post("/api/commands/thread.addToFolder", json={"id": thread["id"], "folder": "Work"})
    wait(lambda: in_location(client, "Work") == ["File me"], "the copy to show")
    assert len(fake.state.boxes["Work"].mails) == 1
    assert len(fake.state.boxes["INBOX"].mails) == 1
    assert status(client)["pulled"] == 1


def test_gmail_removing_a_label_keeps_the_mail_and_deletes_nothing(
    client: TestClient, fake: FakeMail
) -> None:
    fake.state.gmail = True
    add_box(fake, "All Mail", "\\All")
    add_box(fake, "Work")
    raw = make_mail(subject="Labelled")
    fake.state.deliver(raw)
    fake.state.deliver(raw, "All Mail")
    fake.state.deliver(raw, "Work")
    connect(client, fake)
    thread = thread_with(client, "Labelled")
    done = client.post(
        "/api/commands/thread.removeFromFolder", json={"id": thread["id"], "folder": "Work"}
    )
    assert done.status_code == 200, done.text
    wait(lambda: not fake.state.boxes["Work"].mails, "the label to come off")
    assert in_location(client, "INBOX") == ["Labelled"]
    assert len(fake.state.boxes["INBOX"].mails) == 1


def test_gmail_total_counts_each_email_once(client: TestClient, fake: FakeMail) -> None:
    fake.state.gmail = True
    add_box(fake, "All Mail", "\\All")
    add_box(fake, "Spam", "\\Junk")
    for number in range(3):
        raw = make_mail(subject=f"Mail {number}")
        fake.state.deliver(raw)
        fake.state.deliver(raw, "All Mail")
    fake.state.deliver(make_mail(subject="Archived"), "All Mail")
    fake.state.deliver(make_mail(subject="Buy now"), "Spam")
    tested = client.post(
        "/api/commands/mail.accounts.test", json={"profile": fake.profile(), "password": PASSWORD}
    ).json()
    assert tested["total"] == 5
    connect(client, fake)
    wait(lambda: status(client)["pulled"] == 5, "every different email")
    assert status(client)["server_total"] == 5
    # Mail found only in All Mail is what the person archived.
    wait(
        lambda: "Archived" in [row["subject"] for row in threads(client, folder="archive")],
        "archived mail",
    )


def test_spam_stays_in_its_own_folder(client: TestClient, fake: FakeMail) -> None:
    add_box(fake, "Spam", "\\Junk")
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Winner winner", body="Claim your prize"), "Spam")
    wait(lambda: in_location(client, "Spam") == ["Winner winner"], "spam to sync")
    assert not events(client, "mail.received")
    assert not events(client, "mail.needsTriage")
    assert client.post("/api/queries/search.run", json={"query": "prize"}).json()["hits"] == []
    assert [row["subject"] for row in threads(client, folder="junk")] == ["Winner winner"]


def test_nothing_is_ever_deleted_on_the_server_unless_turned_off(
    client: TestClient, fake: FakeMail
) -> None:
    fake.state.deliver(make_mail(subject="Keep on server"))
    connect(client, fake)
    assert status(client)["never_delete"] is True
    thread = thread_with(client, "Keep on server")

    client.post("/api/commands/thread.move", json={"id": thread["id"], "to": "trash"})
    # It's in Trash here straight away, and stays exactly where it was on the server.
    wait(
        lambda: [row["subject"] for row in threads(client, folder="trash")] == ["Keep on server"],
        "it to show in Trash",
    )
    time.sleep(1.5)
    assert len(fake.state.boxes["INBOX"].mails) == 1
    assert not fake.state.boxes["Trash"].mails

    # Saving a draft never leaves a copy to clean up either.
    client.post("/api/commands/drafts.save", json={"subject": "Draft"})
    time.sleep(1.2)
    assert not fake.state.boxes["Drafts"].mails


def test_the_session_itself_refuses_to_delete_or_trash() -> None:
    session = ImapSession.__new__(ImapSession)
    session.never_delete = True
    session.deleting_folders = {"Trash", "Spam"}
    session.client = None  # type: ignore[assignment]
    with pytest.raises(DeleteRefused):
        session.delete(1)
    with pytest.raises(DeleteRefused):
        session.move(1, "Trash")


def test_moving_to_archive_with_nothing_else_downloaded_keeps_it_here(
    client: TestClient, fake: FakeMail
) -> None:
    fake.state.gmail = True
    del fake.state.boxes["Archive"]
    add_box(fake, "All Mail", "\\All")
    raw = make_mail(subject="Archive me")
    fake.state.deliver(raw)
    fake.state.deliver(raw, "All Mail")
    save(client, fake, pull_limit=1)
    thread = thread_with(client, "Archive me")
    client.post("/api/commands/thread.move", json={"id": thread["id"], "to": "archive"})
    wait(lambda: not fake.state.boxes["INBOX"].mails, "the Inbox label to come off")
    assert [row["subject"] for row in threads(client, folder="archive")] == ["Archive me"]


def test_a_conversation_can_be_in_several_categories(client: TestClient, fake: FakeMail) -> None:
    fake.state.deliver(make_mail(subject="Both"))
    connect(client, fake)
    thread = thread_with(client, "Both")
    for name in ("Finance", "Travel"):
        client.post("/api/commands/thread.addCategory", json={"id": thread["id"], "name": name})
    assert [row["subject"] for row in threads(client, folder="all", category="Finance")] == ["Both"]
    assert [row["subject"] for row in threads(client, folder="all", category="Travel")] == ["Both"]
    listed = threads(client, folder="all")[0]
    assert (listed["category"], listed["extra_categories"]) == ("Finance", ["Travel"])
    counted = client.post("/api/queries/categories.list").json()["categories"]
    assert {row["name"]: row["count"] for row in counted}["Travel"] == 1
    client.post("/api/commands/thread.removeCategory", json={"id": thread["id"], "name": "Finance"})
    listed = threads(client, folder="all")[0]
    assert (listed["category"], listed["extra_categories"]) == ("Travel", [])


def test_mail_already_here_is_filed_under_its_other_folders_without_any_budget(
    client: TestClient, fake: FakeMail
) -> None:
    raw = make_mail(subject="Labelled long ago")
    fake.state.deliver(raw)
    connect(client, fake)
    client.post("/api/commands/mail.history.stop", json={})
    downloads = fake.state.fetched_bodies
    # A label that shows up later, holding both mail we have and mail we don't.
    add_box(fake, "Work")
    fake.state.deliver(raw, "Work")
    fake.state.deliver(make_mail(subject="Not downloaded"), "Work")
    wait(lambda: "Work" in folders(client), "the label to appear")
    wait(lambda: folders(client)["Work"]["here"] >= 1, "the mail already here to be filed")
    assert fake.state.fetched_bodies <= downloads + 1
    assert "Labelled long ago" in in_location(client, "Work")


def test_images_follow_the_setting_and_each_senders_exception(
    client: TestClient, fake: FakeMail
) -> None:
    fake.state.deliver(make_mail(subject="Pictures", html='<img src="https://cdn.example/a.jpg">'))
    connect(client, fake)
    thread = thread_with(client, "Pictures")

    def shown() -> bool:
        view = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()
        return view["messages"][0]["show_images"]

    assert shown() is True
    client.post("/api/commands/settings.update", json={"remote_images": "block"})
    assert shown() is False
    sender = client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][0]
    client.post(
        "/api/commands/mail.images.sender",
        json={"address": sender["from_addr"].upper(), "allow": True},
    )
    assert shown() is True


def test_a_logo_seen_often_enough_leaves_documents_including_earlier_copies(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    logo = ("company-banner-final.png", "image/png", b"x" * 90_000)
    for number in range(2):
        fake.state.deliver(make_mail(subject=f"Footer {number}", attachments=[logo]))
    report = ("report.pdf", "application/pdf", b"%PDF-1.4 real report")
    fake.state.deliver(make_mail(subject="Has a report", attachments=[report]))
    thread_with(client, "Has a report")

    def names() -> list[str]:
        rows = client.post("/api/queries/documents.list", json={"source": "email"}).json()
        return [row["name"] for row in rows["documents"]]

    wait(lambda: names().count("company-banner-final.png") == 2, "the first two copies")
    fake.state.deliver(make_mail(subject="Footer 2", attachments=[logo]))
    thread_with(client, "Footer 2")
    wait(lambda: "company-banner-final.png" not in names(), "the logo to leave Documents")
    assert "report.pdf" in names()
    assert not thread_with(client, "Footer 0")["has_attachments"]


def test_sound_settings_save_and_come_back(client: TestClient) -> None:
    saved = client.post(
        "/api/commands/settings.update", json={"sound_muted": True, "sound_off": ["reminder"]}
    )
    assert saved.status_code == 200, saved.text
    read = client.post("/api/queries/settings.get").json()
    assert (read["sound_muted"], read["sound_off"]) == (True, ["reminder"])
