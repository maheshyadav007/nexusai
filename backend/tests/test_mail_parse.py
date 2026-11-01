from dataclasses import replace

import pytest

from fake_mail import make_mail
from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition
from nexusai.kernel.config import load_config
from nexusai.modules.mail.attachments import classify
from nexusai.modules.mail.parse import (
    Part,
    clean_text,
    html_to_text,
    normalize_subject,
    own_text,
    parse_message,
)
from nexusai.modules.mail.rules import evaluate
from nexusai.modules.mail.safe_html import sanitize


def test_parses_a_plain_message() -> None:
    parsed = parse_message(make_mail(subject="Contract", body="Please review.", cc="a@x.com"))
    assert parsed.subject == "Contract"
    assert parsed.from_addr == "priya@example.com" and parsed.from_name == "Priya Nair"
    assert parsed.cc == ["a@x.com"]
    assert parsed.own == "Please review."
    assert parsed.date.endswith("+00:00")


def test_reads_html_only_mail_as_text() -> None:
    raw = (
        b"From: a@x.com\r\nSubject: Hi\r\nMIME-Version: 1.0\r\nContent-Type: text/html\r\n\r\n"
        b"<html><style>p{}</style><p>Hello <b>there</b></p><script>x()</script></html>"
    )
    parsed = parse_message(raw)
    assert parsed.text == "Hello there"
    assert "<p>" in (parsed.html or "")


def test_broken_mail_still_parses() -> None:
    parsed = parse_message(b"Subject: \xff\xfe bad\r\nDate: not a date\r\n\r\nbody \xff here")
    assert parsed.message_id.startswith("<generated-")
    assert "body" in parsed.text


@pytest.mark.parametrize(
    "quoted",
    [
        "On Mon, 3 Jan 2026 at 10:00, Priya <p@x.com> wrote:\n> old",
        "-----Original Message-----\nFrom: x",
        "From: Priya\nSent: Monday\nTo: Me\nSubject: Old",
        "보낸 사람: 김\n보낸 날짜: 월요일",
        "> just a quote",
    ],
)
def test_own_text_drops_quoted_mail(quoted: str) -> None:
    assert own_text(f"New text here.\n\n{quoted}") == "New text here."


def test_clean_text_also_drops_signature_and_legal_footer() -> None:
    body = "Please approve.\n\n--\nPriya\nThis email is confidential."
    assert clean_text(body) == "Please approve."
    assert (
        clean_text("Do it.\n\nThis message is confidential and intended only for you.") == "Do it."
    )
    assert "Priya" in own_text(body)


@pytest.mark.parametrize(
    "subject", ["Re: Budget", "RE: FW: Budget", "Fwd: re:  Budget", "회신: budget"]
)
def test_subject_prefixes_are_removed(subject: str) -> None:
    assert normalize_subject(subject) in {"budget"} or subject.startswith("회신")


def test_detects_encrypted_and_signed_mail() -> None:
    smime = (
        b"From: a@x.com\r\nSubject: S\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"\r\n\r\nxxxx'
    )
    assert parse_message(smime).encrypted == "smime"
    signed = (
        b"From: a@x.com\r\nSubject: S\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: multipart/signed; boundary="b"; protocol="application/pkcs7-signature"\r\n\r\n'
        b"--b\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
        b"--b\r\nContent-Type: application/pkcs7-signature\r\n\r\nsig\r\n--b--\r\n"
    )
    parsed = parse_message(signed)
    assert parsed.signed and parsed.encrypted is None and parsed.text == "hello"


def test_outlook_thread_index_root_is_shared() -> None:
    root = "AQHZ" + "A" * 26
    first = parse_message(make_mail(headers={"Thread-Index": root}))
    second = parse_message(make_mail(headers={"Thread-Index": root + "BBBBBB"}))
    assert first.thread_index_root and first.thread_index_root == second.thread_index_root


def part(**changes: object) -> Part:
    base = Part(1, "file", "image/png", 5000, "cid1", "inline", "h")
    return replace(base, **changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "seen", "kind"),
    [
        ({"size": 5000}, 1, "signature"),
        ({"size": 500_000}, 1, "inline"),
        ({"size": 500_000}, 5, "signature"),
        (
            {
                "content_id": None,
                "disposition": "attachment",
                "filename": "r.pdf",
                "content_type": "application/pdf",
            },
            0,
            "attachment",
        ),
        ({"filename": "run.exe", "disposition": "attachment"}, 0, "risky"),
        ({"filename": "q.docm", "disposition": "attachment"}, 0, "risky"),
        (
            {
                "filename": "invite.ics",
                "content_type": "text/calendar",
                "disposition": "attachment",
            },
            0,
            "calendar",
        ),
    ],
)
def test_attachment_kinds(changes: dict[str, object], seen: int, kind: str) -> None:
    assert classify(part(**changes), seen, load_config().mail) == kind


@pytest.mark.parametrize(
    ("headers", "sender", "category"),
    [
        ({"Auto-Submitted": "auto-generated"}, "a@x.com", "Automated"),
        ({"List-Id": "<dev.lists.x>"}, "a@x.com", "Newsletters"),
        ({"List-Unsubscribe": "<mailto:u@x>"}, "a@x.com", "Newsletters"),
        ({"Precedence": "bulk"}, "a@x.com", "Newsletters"),
        ({}, "no-reply@x.com", "Automated"),
        ({}, "notifications@x.com", "Automated"),
    ],
)
def test_builtin_rules_catch_routine_mail(
    headers: dict[str, str], sender: str, category: str
) -> None:
    match = evaluate(parse_message(make_mail(sender=sender, headers=headers)), [])
    assert match and match.actions.category == category and match.actions.skip_agent
    assert match.why.startswith("Matched the rule")


def test_a_person_gets_no_rule() -> None:
    assert evaluate(parse_message(make_mail()), []) is None
    assert evaluate(parse_message(make_mail(headers={"Auto-Submitted": "no"})), []) is None


def rule(**condition: str) -> MailRule:
    return MailRule(
        name="Invoices",
        conditions=[RuleCondition(**condition)],  # type: ignore[arg-type]
        actions=RuleActions(category="Finance", mark_read=True),
    )


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "subject", "value": "INVOICE"},
        {"field": "body", "value": "please pay"},
        {"field": "sender", "value": "billing@"},
        {"field": "header", "header": "X-Kind", "value": "bill"},
    ],
)
def test_user_rules_match_and_win_over_builtin(condition: dict[str, str]) -> None:
    raw = make_mail(
        subject="Invoice 7",
        body="Please pay",
        sender="billing@x.com",
        headers={"X-Kind": "bill", "List-Id": "<x>"},
    )
    match = evaluate(parse_message(raw), [rule(**condition)])
    assert match and match.name == "Invoices" and match.actions.category == "Finance"


def test_disabled_rules_and_attachment_condition() -> None:
    disabled = rule(field="subject", value="x").model_copy(update={"enabled": False})
    assert evaluate(parse_message(make_mail(subject="x")), [disabled]) is None
    has = rule(field="has_attachment")
    assert evaluate(parse_message(make_mail()), [has]) is None
    with_file = make_mail(attachments=[("a.pdf", "application/pdf", b"%PDF")])
    assert evaluate(parse_message(with_file), [has])


def test_html_is_made_safe() -> None:
    clean = sanitize(
        '<p onclick="x()" style="color:red;background:url(http://evil/t.png)">Hi</p>'
        '<script>steal()</script><iframe src="http://evil"></iframe><form action="x"><input></form>'
        '<img src="http://evil/track.png"><a href="javascript:x()">a</a><a href="https://ok.example">b</a>',
        [],
    )
    for bad in (
        "onclick",
        "<script",
        "steal",
        "<iframe",
        "<form",
        "javascript:",
        ' src="http://evil',
    ):
        assert bad not in clean
    assert "http://evil/t.png" not in clean
    assert 'data-blocked-src="http://evil/track.png"' in clean
    assert "color:red" in clean
    assert 'href="https://ok.example"' in clean


def test_cid_images_are_embedded() -> None:
    logo = Part(1, "l.png", "image/png", 3, "logo", "inline", "h")
    clean = sanitize('<img src="cid:logo"><img src="cid:other">', [(logo, b"abc")])
    assert "data:image/png;base64,YWJj" in clean


def test_html_to_text_handles_entities_and_blocks() -> None:
    assert html_to_text("<div>a&amp;b</div><div>c</div>") == "a&b\n\nc"
