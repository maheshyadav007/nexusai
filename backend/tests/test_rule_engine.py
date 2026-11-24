"""The rule engine every email passes before the AI: a batch in, one decision per email out, with
what matched and why. Tags and senders come from the mailbox; nothing is named in advance."""

from fake_mail import make_mail
from nexusai.contracts.mail import MailMe, MailRule, RuleActions, RuleCondition
from nexusai.modules.mail import mentions, rules, sort_rules, subject_kinds
from nexusai.modules.mail.parse import parse_message, tags_of
from nexusai.modules.mail.sort_rules import Seen

OWNER = "me@example.com"


def mail(subject: str, sender: str = "plm@corp.example", body: str = "Done.", **extra: str):  # type: ignore[no-untyped-def]
    return parse_message(make_mail(subject=subject, sender=sender, to=OWNER, body=body, **extra))


def test_every_tag_is_read_without_its_number() -> None:
    assert tags_of("Re: [PLM-1104][Reminder] Due") == ("PLM", "Reminder")
    assert tags_of("[3GPP Briefing] RAN2") == ("3GPP Briefing",)
    assert tags_of("[Swarm] Review 12 [Invitation]") == ("Swarm", "Invitation")
    assert tags_of("[회의] 안내") == ("회의",)
    # A list's number is no tag, and the same tag twice counts once.
    assert tags_of("[123] Digest") == ()
    assert tags_of("[plm] a [PLM] b") == ("plm",)


def test_a_batch_gets_one_decision_each_with_what_matched() -> None:
    plm = MailRule(
        name="Sorted: Automated/PLM: [PLM]",
        conditions=[RuleCondition(field="tag", value="PLM")],
        actions=RuleActions(
            category="Automated/PLM", skip_agent=True, read_replies=True, mentions=[OWNER]
        ),
    )
    engine = rules.Engine([plm])
    batch = [
        mail("[Reminder][PLM-88] Task due"),
        mail("Re: [PLM-88] Task due", sender="kim@corp.example"),
        mail("[PLM-89] Assigned", body=f"Assigned to {OWNER} today.\nMore\nMore\nFooter"),
        mail("Lunch?", sender="kim@corp.example"),
    ]
    quiet, reply, named, person = engine.decide(batch)
    assert not quiet.reaches_ai and quiet.rule == plm.name and quiet.category == "Automated/PLM"
    # The folder is the gate: a reply or mail that names the person, filed where the AI doesn't
    # read, stays there too, even under an old rule that still says otherwise.
    assert not reply.reaches_ai and reply.rule == plm.name
    assert not named.reaches_ai and named.rule == plm.name
    assert person.reaches_ai and person.rule is None
    assert quiet.as_dict()["why"] == f"Hidden from AI by “{plm.name}”"
    # One email is a batch of one.
    assert engine.decide([batch[0]]) == [quiet]


def test_switched_off_everything_reaches_the_ai_and_nothing_is_filed() -> None:
    every = MailRule(
        name="All",
        conditions=[RuleCondition(field="subject", value="")],
        actions=RuleActions(category="Hidden", skip_agent=True),
    )
    decisions = rules.Engine([every], on=False).decide(
        [mail("[PLM] x"), mail("hi", headers={"List-Unsubscribe": "<mailto:u@x>"})]
    )
    assert all(d.reaches_ai and d.match is None for d in decisions)


def test_a_tag_becomes_a_rule_only_where_it_belongs_to_the_category() -> None:
    tool = ["plm@corp.example", "plm-prod2@corp.example"]
    box = [
        *(Seen(tool[n % 2], f"[Reminder][PLM-{n}] Task due", False) for n in range(8)),
        # Other tools remind too, so [Reminder] marks no one category.
        *(Seen("hr@corp.example", f"[Reminder] Timesheet {n}", False) for n in range(8)),
        # A person's reply carries the tag too, and never decides it.
        Seen("kim@corp.example", "Re: [PLM-3] Task due", True),
    ]
    assert sort_rules.own_tag(tool, box) == "PLM"
    made = sort_rules.rules_for("Automated/PLM", tool, box, owner=OWNER)
    assert [rule.conditions[0].field for rule in made] == ["sender_exact", "sender_exact", "tag"]
    tag_rule = made[-1]
    assert not any(rule.actions.read_replies or rule.actions.mentions for rule in made)
    assert rules.describe_rule(tag_rule) == (
        "If the subject carries the tag [PLM] → file in Automated/PLM, the AI skips it"
    )
    # A sender with no tag of its own gets only its address rule.
    hr = sort_rules.rules_for("Automated/HR", ["hr@corp.example"], box)
    assert [rule.conditions[0].field for rule in hr] == ["sender_exact"]


def test_a_new_address_of_the_same_tool_is_still_filed_by_its_tag() -> None:
    box = [Seen("plm@corp.example", f"[PLM-{n}] Released", False) for n in range(5)]
    engine = rules.Engine(sort_rules.rules_for("Automated/PLM", ["plm@corp.example"], box))
    (moved,) = engine.decide([mail("[PLM-77] Released", sender="plm-notify9@corp.example")])
    assert not moved.reaches_ai and moved.category == "Automated/PLM"


def test_a_sender_with_kinds_of_mail_gets_a_rule_for_each_and_the_odd_one_reaches_the_ai() -> None:
    bank = "alerts@bank.example"
    subjects = [
        *(f"Your OTP for login is {n}" for n in range(6)),
        *(f"Mahesh, your statement for {month} is ready" for month in ("Oct", "Nov", "Dec")),
        "Rs 2,450.00 debited from your account XX8812 on 18-Nov",
        "Rs 120 debited from your account XX8812 on 19-Nov",
        "We have updated our privacy policy",
    ]
    found = subject_kinds.find(
        subjects, subject_kinds.own_words("Mahesh Yadav", "mahesh@x.example")
    )
    assert [(k.words, k.count) for k in found.kinds] == [
        (("login", "otp"), 6),
        (("ready", "statement"), 3),
        (("account", "debited", "rs"), 2),
    ]
    assert found.odd == 1
    box = [Seen(bank, subject, False) for subject in subjects]
    made = sort_rules.rules_for("Bank", [bank], box, kinds={bank: found.kinds})
    assert [[(c.field, c.value) for c in rule.conditions] for rule in made][0] == [
        ("sender_exact", bank),
        ("subject_words", "login otp"),
    ]
    assert rules.describe_rule(made[0]) == (
        "If it's from alerts@bank.example and the subject has the words “login otp”"
        " → file in Bank, the AI skips it"
    )
    otp, debit, new = rules.Engine(made).decide(
        [
            mail("OTP 99 for your login", sender=bank),
            mail("Rs 5 debited from your account XX1", sender=bank),
            mail("Your card is blocked", sender=bank),
        ]
    )
    assert not otp.reaches_ai and not debit.reaches_ai
    # Something new from it fits no kind, so the AI reads it.
    assert new.reaches_ai


def test_a_sender_without_kinds_keeps_one_rule_for_all_its_mail() -> None:
    shop = "news@shop.example"
    subjects = ["Big sale this weekend", "New arrivals for you", "Last chance: 40% off", "Hello"]
    assert subject_kinds.find(subjects).kinds == ()
    made = sort_rules.rules_for("Shopping", [shop], [Seen(shop, s, False) for s in subjects])
    assert [[c.field for c in rule.conditions] for rule in made] == [["sender_exact"]]


def test_a_tag_splits_kinds_and_two_emails_are_enough() -> None:
    found = subject_kinds.find(
        [
            "[PLM] ECO-1 released",
            "[PLM] ECO-2 released",
            "[HR] ECO-3 released",
            "[HR] ECO-4 released",
        ]
    )
    assert [(k.tag, k.words, k.count) for k in found.kinds] == [
        ("hr", ("eco", "released"), 2),
        ("plm", ("eco", "released"), 2),
    ]


def test_a_ticket_tag_is_one_kind_and_a_shared_word_holds_changing_names() -> None:
    tickets = subject_kinds.find(
        [
            f"[RND-{n}] {title}"
            for n, title in enumerate(["Slow boot", "Modem drops", "Camera lag"] * 2)
        ]
    )
    assert [(k.tag, k.words, k.count) for k in tickets.kinds] == [("rnd", (), 6)]
    edits = subject_kinds.find(
        [f'{who} edited "{page}"' for who, page in [("Rahul Menon", "Roadmap"), ("Sneha Reddy", "Guide"),
                                                    ("Pooja Hegde", "Rota"), ("Varun Kapoor", "Template")]]
    )  # fmt: skip
    assert [(k.words, k.count) for k in edits.kinds] == [(("edited",), 4)]


def test_a_sender_whose_kinds_explain_little_of_its_mail_has_none() -> None:
    offers = [f"Mahesh, {line}" for line in ["fresh colours", "turn moving day", "cleaning stuck",
                                              "a weekend for you", "deals inside", "new in town"]]  # fmt: skip
    found = subject_kinds.find([*offers, "Your OTP is 1", "Your OTP is 2"])
    # One kind covering a quarter of its mail is no ordinary: all of it is one, under one rule.
    assert (found.kinds, found.odd) == ((), 0)


ME = MailMe(
    names=["Mahesh Yadav", "Mahesh", "M. Yadav"],
    addresses=["m.yadav@samsung.com"],
    ids=["myadav01", "m.yadav"],
    not_you=["Maheshwari"],
)
QUOTED = (
    "\n\nOn Mon, 23 Nov 2026 at 10:00, PLM System <plm-noreply@samsung.com> wrote:\n"
    "> Dear Mahesh Yadav, ECO-1112 is assigned to you.\n"
)
PLM = MailRule(
    name="PLM",
    match="any",
    conditions=[
        RuleCondition(field="sender_exact", value="plm-noreply@samsung.com"),
        RuleCondition(field="tag", value="PLM"),
        RuleCondition(field="tag", value="RND"),
        RuleCondition(field="sender_exact", value="jira@samsung.com"),
    ],
    actions=RuleActions(category="PLM", skip_agent=True),
)


def reply(
    body: str,
    sender: str = "Rahul Menon <rahul.m@samsung.com>",
    subject: str = "RE: [PLM] ECO-1112",
):  # type: ignore[no-untyped-def]
    return parse_message(
        make_mail(subject=subject, sender=sender, to="m.yadav@samsung.com", body=body,
                  in_reply_to="<root@x>")
    )  # fmt: skip


def test_tool_mail_that_greets_the_person_stays_hidden() -> None:
    engine = rules.Engine([PLM], me=ME)
    tool = [
        mail("[PLM] ECO-1112 assigned", sender="plm-noreply@samsung.com",
             body="Dear Mahesh Yadav,\nECO-1112 is assigned to you for review."),
        mail("[RND-1112] Build failed", sender="jira@samsung.com", body="Dear myadav01,\nIt failed."),
        reply("Dear Mahesh Yadav, status changed to Approved.", sender="plm-noreply@samsung.com"),
    ]  # fmt: skip
    assert [d.reaches_ai for d in engine.decide(tool)] == [False, False, False]


def test_a_person_replying_on_hidden_mail_who_names_the_person_reaches_the_ai() -> None:
    engine = rules.Engine([PLM], me=ME)
    said = {
        "@Mahesh please check the BOM before Friday.": "@Mahesh please check the BOM before Friday.",
        "Mahesh, can you review the drawing?": "Mahesh, can you review the drawing?",
        "Hi Mahesh,\nI think your change broke it.": "Hi Mahesh,",
        "adding mahesh yadav for visibility.": "adding mahesh yadav for visibility.",
        "Looping m.yadav@samsung.com here.": "Looping m.yadav@samsung.com here.",
        "Assigning to myadav01.": "Assigning to myadav01.",
        "Looks like Mahesh's change caused this.": "Looks like Mahesh's change caused this.",
        "@m.yadav can you take a look?": "@m.yadav can you take a look?",
        "Need input from M. Yadav on this.": "Need input from M. Yadav on this.",
        "Mahesh FYI, need your sign-off.": "Mahesh FYI, need your sign-off.",
    }
    for body, quote in said.items():
        decision = engine.decide([reply(body + QUOTED)])[0]
        assert decision.reaches_ai and decision.category == "PLM", body
        assert decision.named == quote
        assert "Rahul Menon named you" in decision.why
    forwarded = reply("Mahesh FYI.", sender="Lead <lead@samsung.com>", subject="FW: [PLM] ECO-1112")
    assert engine.decide([forwarded])[0].reaches_ai


def test_replies_that_dont_name_the_person_stay_hidden() -> None:
    engine = rules.Engine([PLM], me=ME)
    for body in [
        "Approved from my side.",  # named only in the quoted mail
        "Team, the meeting moved to 3pm.",
        "Maheshwari will handle this.",  # someone the person said isn't them
        "Mahesh Kumar, please update the BOM.",  # another Mahesh
        "Approved.\n\nRegards,\nRahul\ncc list: Mahesh Yadav",  # in the signature
    ]:
        assert not engine.decide([reply(body + QUOTED)])[0].reaches_ai, body
    # Without knowing who the person is, nothing is named.
    assert not rules.Engine([PLM]).decide([reply("@Mahesh please check" + QUOTED)])[0].reaches_ai


def test_a_tool_passing_on_a_mention_reaches_the_ai() -> None:
    told = mail("[RND-1112] Rahul Menon mentioned you", sender="jira@samsung.com",
                body="Rahul Menon mentioned you on RND-1112")  # fmt: skip
    decision = rules.Engine([PLM], me=ME).decide([told])[0]
    assert decision.reaches_ai and decision.named == "[RND-1112] Rahul Menon mentioned you"


def test_any_matches_one_condition_and_an_exception_leaves_mail_alone() -> None:
    rule = PLM.model_copy(
        update={"exceptions": [RuleCondition(field="subject_words", value="escalated")]}
    )
    assert rules.rule_matches(rule, mail("[PLM] ECO-1 approved", sender="x@y.com"))
    assert not rules.rule_matches(rule, mail("[PLM] ECO-1 escalated", sender="x@y.com"))
    assert not rules.rule_matches(rule.model_copy(update={"match": "all"}), mail("[PLM] ECO-1"))
    blank = rule.model_copy(
        update={"exceptions": [RuleCondition(field="subject_words", value=" ")]}
    )
    assert rules.rule_matches(blank, mail("[PLM] ECO-1 approved"))
    to = RuleCondition(field="to", value="team@samsung.com")
    assert rules.rule_matches(
        MailRule(name="t", conditions=[to], actions=RuleActions()),
        parse_message(make_mail(to="team@samsung.com, me@x.com")),
    )
    assert rules.describe_rule(rule) == (
        "If it's from plm-noreply@samsung.com or the subject carries the tag [PLM] or the subject"
        " carries the tag [RND] or it's from jira@samsung.com, except when the subject has the"
        " words “escalated” → file in PLM, the AI skips it"
    )


def test_what_the_account_says_about_the_person() -> None:
    me = mentions.found("Mahesh Yadav", ["m.yadav@samsung.com"])
    assert me.names == ["Mahesh Yadav", "Mahesh"]
    assert me.ids == ["m.yadav"]
    assert mentions.name_from(["Mahesh Yadav", "Mahesh Yadav", "mahesh@x.com", "M"]) == (
        "Mahesh Yadav"
    )
