"""The rule engine every email passes before the AI: a batch in, one decision per email out, with
what matched and why. Tags and senders come from the mailbox; nothing is named in advance."""

from fake_mail import make_mail
from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition
from nexusai.modules.mail import rules, sort_rules
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


def test_a_sender_whose_subjects_start_the_same_ways_gets_a_rule_for_each() -> None:
    bank = "alerts@bank.example"
    box = [
        *(Seen(bank, f"Your OTP for login is {n}", False) for n in range(6)),
        *(Seen(bank, f"[Bank] Your statement for month {n}", False) for n in range(3)),
        Seen(bank, "We have updated our privacy policy", False),
    ]
    ways = sort_rules.subject_starts([seen.subject for seen in box])
    made = sort_rules.rules_for("Bank", [bank], box, starts={bank: ways})
    assert [[(c.field, c.value) for c in rule.conditions] for rule in made] == [
        [("sender_exact", bank), ("subject", "your otp for")],
        [("sender_exact", bank), ("subject", "your statement for")],
    ]
    assert rules.describe_rule(made[0]) == (
        "If it's from alerts@bank.example and the subject has “your otp for”"
        " → file in Bank, the AI skips it"
    )
    engine = rules.Engine(made)
    otp, new = engine.decide(
        [mail("Your  OTP for login is 99", sender=bank), mail("Your card is blocked", sender=bank)]
    )
    assert not otp.reaches_ai and otp.category == "Bank"
    # Something new from it isn't what was sorted, so the AI reads it.
    assert new.reaches_ai


def test_a_sender_whose_subjects_vary_keeps_one_rule_for_all_its_mail() -> None:
    shop = "news@shop.example"
    box = [Seen(shop, subject, False) for subject in
           ["Big sale this weekend", "New arrivals for you", "Last chance: 40% off", "Hello again"]]  # fmt: skip
    assert sort_rules.subject_starts([seen.subject for seen in box]) == []
    made = sort_rules.rules_for("Shopping", [shop], box, starts={shop: []})
    assert [[c.field for c in rule.conditions] for rule in made] == [["sender_exact"]]


def test_a_subject_starts_after_its_tags_and_before_its_numbers() -> None:
    assert sort_rules.start_of("[PLM] Workflow task CR-123 is due") == "workflow task cr"
    assert sort_rules.start_of("Re: [HR] Your  payslip for Oct") == "your payslip for"
    assert sort_rules.start_of("Order #123 shipped") == ""
    assert sort_rules.start_of("Invoice: March 2026") == "invoice march"
