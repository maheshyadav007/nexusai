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
    assert reply.reaches_ai and reply.exception.startswith("A reply")
    assert named.reaches_ai and named.exception == "It names you"
    assert person.reaches_ai and person.rule is None
    assert quiet.as_dict()["why"] == f"Kept from the AI by “{plm.name}”"
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
    made = sort_rules.rules_for("Automated/PLM", tool, box, mentions=[OWNER], owner=OWNER)
    assert [rule.conditions[0].field for rule in made] == ["sender_exact", "sender_exact", "tag"]
    tag_rule = made[-1]
    assert tag_rule.actions.read_replies and not made[0].actions.read_replies
    assert rules.describe_rule(tag_rule) == (
        "If the subject carries the tag [PLM] → file in Automated/PLM, the AI skips it,"
        " except replies and mail that names you"
    )
    # A sender with no tag of its own gets only its address rule.
    hr = sort_rules.rules_for("Automated/HR", ["hr@corp.example"], box)
    assert [rule.conditions[0].field for rule in hr] == ["sender_exact"]


def test_a_new_address_of_the_same_tool_is_still_filed_by_its_tag() -> None:
    box = [Seen("plm@corp.example", f"[PLM-{n}] Released", False) for n in range(5)]
    engine = rules.Engine(sort_rules.rules_for("Automated/PLM", ["plm@corp.example"], box))
    (moved,) = engine.decide([mail("[PLM-77] Released", sender="plm-notify9@corp.example")])
    assert not moved.reaches_ai and moved.category == "Automated/PLM"
