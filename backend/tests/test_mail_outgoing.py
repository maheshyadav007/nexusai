"""Files going out with mail, forwards, suggested addresses, the signature, and inline images."""
# ruff: noqa: F811

import email
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.modules.agent import module as agent_module
from nexusai.modules.mail.parse import Part
from nexusai.modules.mail.safe_html import sanitize
from test_mail_sync import client, connect, fake, thread_with, wait  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\nimage"


def _sent_files(fake: FakeMail) -> dict[str, bytes]:
    message = email.message_from_bytes(fake.sent[-1]["raw"])
    return {
        part.get_filename(): part.get_payload(decode=True)
        for part in message.walk()
        if part.get_filename()
    }


def _first_message(client: TestClient, subject: str) -> dict[str, Any]:
    thread = thread_with(client, subject)
    return client.post("/api/queries/thread.get", json={"id": thread["id"]}).json()["messages"][0]


def test_a_file_added_in_the_composer_goes_with_the_mail_and_is_let_go(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    added = client.post(
        "/api/mail/draft-attachment", params={"name": "plan.pdf"}, content=b"%PDF-1 plan"
    ).json()
    assert added["name"] == "plan.pdf" and added["size"] == 11 and added["upload"]
    draft = {
        "to": [{"address": "sam@x.com"}],
        "subject": "Plan",
        "body": "The plan is attached.",
        "attachments": [added],
    }
    # It says attached, and something is, so the check stays quiet.
    checked = client.post("/api/queries/mail.checkSend", json={"draft": draft}).json()
    assert not [p for p in checked["problems"] if p["check"] == "missing_attachment"]
    assert client.post("/api/commands/mail.send", json={"draft": draft}).status_code == 200
    assert _sent_files(fake) == {"plan.pdf": b"%PDF-1 plan"}
    # Sent, so the file isn't kept, and sending it again says so plainly.
    again = client.post("/api/commands/mail.send", json={"draft": draft})
    assert again.status_code == 422 and "plan.pdf" in again.json()["message"]


def test_attachments_over_the_limit_are_refused_before_sending(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    big = client.post(
        "/api/mail/draft-attachment",
        params={"name": "big.bin"},
        content=b"x" * (18 * 1024 * 1024 + 1),
    )
    assert big.status_code == 413 and "MB" in big.json()["message"]


def test_a_forward_carries_the_original_and_its_attachments(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(
        make_mail(
            subject="Contract",
            body="Signed copy attached.",
            attachments=[("contract.pdf", "application/pdf", b"%PDF-signed")],
        )
    )
    message = _first_message(client, "Contract")
    forward = client.post("/api/queries/mail.forwardDraft", json={"message_id": message["id"]})
    draft = forward.json()["draft"]
    assert draft["subject"] == "Fwd: Contract"
    assert "Forwarded message" in draft["body"] and "Signed copy attached." in draft["body"]
    assert "priya@example.com" in draft["body"]
    assert [a["name"] for a in draft["attachments"]] == ["contract.pdf"]
    draft["to"] = [{"address": "legal@x.com"}]
    assert client.post("/api/commands/mail.send", json={"draft": draft}).status_code == 200
    assert _sent_files(fake) == {"contract.pdf": b"%PDF-signed"}


def test_suggested_addresses_put_people_you_write_to_first(
    client: TestClient, fake: FakeMail
) -> None:
    connect(client, fake)
    fake.state.deliver(make_mail(subject="Hi", sender="Priya Nair <priya@example.com>"))
    fake.state.deliver(make_mail(subject="Deal", sender="Pritam Shah <pritam@shop.example>"))
    thread_with(client, "Deal")
    for _ in range(2):
        client.post(
            "/api/commands/mail.send",
            json={
                "draft": {"to": [{"address": "prisha@team.example"}], "subject": "s", "body": "b"}
            },
        )

    def ranked() -> list[str]:
        result = client.post("/api/queries/mail.suggestRecipients", json={"text": "pri"}).json()
        return [person["address"] for person in result["people"]]

    addresses = wait(lambda: (r := ranked()) and r[0] == "prisha@team.example" and r, "sent copies")
    assert set(addresses) >= {"prisha@team.example", "priya@example.com", "pritam@shop.example"}
    named = client.post("/api/queries/mail.suggestRecipients", json={"text": "shah"}).json()
    assert named["people"][0] == {"name": "Pritam Shah", "address": "pritam@shop.example"}
    assert client.post("/api/queries/mail.suggestRecipients", json={"text": "p"}).json() == {
        "people": []
    }


def _part(index: int, name: str, kind: str, cid: str | None) -> Part:
    return Part(index, name, kind, 0, cid, "inline", "h")


def test_inline_pictures_are_found_however_the_email_links_them() -> None:
    shown = sanitize(
        '<img src="cid:Logo%40Mail"><img src="image002.png"><img src="cid:gone">'
        '<img src="images/line.jpg"><img src="{{@imagesrc}}"><img alt="x">'
        '<img src="//cdn.example/a.png"><img src="assets.example.com/b.png">',
        [
            (_part(1, "logo.png", "application/octet-stream", "<logo@mail>"), PNG),
            (_part(2, "image002.png", "image/png", None), PNG),
        ],
        missing := [],
    )
    assert shown.count('src="data:image/png;base64,') == 2
    assert 'data-blocked-src="https://cdn.example/a.png"' in shown
    assert 'data-blocked-src="https://assets.example.com/b.png"' in shown
    # Nothing is left to draw a broken icon.
    assert shown.count("<img") == 4
    assert sorted(missing) == [
        "image address that can't load",
        "image address that can't load",
        "image with no address",
        "inline image not in the email",
    ]


def test_an_agent_reply_can_attach_a_mail_file_and_forward_with_the_signature(
    client: TestClient, fake: FakeMail
) -> None:
    from nexusai.modules.agent import tools

    connect(client, fake)
    client.post("/api/commands/profile.update", json={"signature": "Asha Rao\nAudit lead"})
    fake.state.deliver(
        make_mail(subject="Invoice", attachments=[("inv.pdf", "application/pdf", b"%PDF-inv")])
    )
    message = _first_message(client, "Invoice")
    thread_id = thread_with(client, "Invoice")["id"]
    ctx = agent_module.current().ctx
    built = {tool.name: tool for tool in tools.build_tools(ctx, "s", tools.RunControl())}
    said = built["draft_reply"].func(  # type: ignore[misc]
        thread_id=thread_id,
        body="Here it is.",
        tool_call_id="c1",
        attachments=[f"m:{message['id']}:{message['attachments'][0]['index']}", "m:999:1"],
    )
    assert "Attached: inv.pdf" in said and "m:999:1" in said
    said = built["draft_forward"].func(  # type: ignore[misc]
        thread_id=thread_id, to=["ap@x.com"], note="For payment.", tool_call_id="c2"
    )
    assert "inv.pdf" in said
    drafts = client.post("/api/queries/drafts.list").json()["drafts"]
    reply = next(d for d in drafts if d["subject"] == "Re: Invoice")
    forward = next(d for d in drafts if d["subject"] == "Fwd: Invoice")
    assert reply["body"].endswith("-- \nAsha Rao\nAudit lead")
    assert [a["name"] for a in reply["attachments"]] == ["inv.pdf"]
    assert forward["body"].startswith("For payment.\n\n-- \nAsha Rao")
    assert [a["name"] for a in forward["attachments"]] == ["inv.pdf"]
    assert client.post("/api/commands/mail.send", json={"draft": forward}).status_code == 200
    assert _sent_files(fake) == {"inv.pdf": b"%PDF-inv"}
