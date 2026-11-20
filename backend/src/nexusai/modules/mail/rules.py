"""Fixed rules that run before any model, so routine mail costs nothing to handle."""

import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition, RuleSet
from nexusai.kernel.files import replace_file
from nexusai.modules.mail import grouping
from nexusai.modules.mail.parse import SUBJECT_PREFIX, ParsedMessage, tags_of

NO_REPLY = re.compile(
    r"(^|[._+-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?)@", re.I
)


# Systems say so in their own headers, and they aren't marketing even with an unsubscribe link.
SYSTEM_NOTICE_HEADERS = (
    "x-github-reason",
    "x-gitlab-project",
    "x-jira-fingerprint",
    "x-atlassian-mail-type",
    "x-bitbucket-eventtype",
    "x-jenkins-job",
)
SOCIAL_DOMAINS = (
    "facebookmail.com",
    "linkedin.com",
    "twitter.com",
    "instagram.com",
    "reddit.com",
    "pinterest.com",
    "quora.com",
)
PUBLIC_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "proton.me",
    }
)


# A conversation filed by a rule the person can see (a sender or subject prefix) belongs to that
# rule: the AI neither files it elsewhere nor learns from it. Folders filed by headers alone, like
# Updates, are guesses, and stay open to a closer look. Needs the threads table as `t`.
FILED_BY_RULE = (
    "(t.category_source='rule' AND EXISTS (SELECT 1 FROM mail_categories c WHERE c.name=t.category"
    " AND (COALESCE(c.sender,'')!='' OR COALESCE(c.subject,'')!='')))"
)

# Automated mail goes unjudged, unless what it says could cost the person something.
WORTH_A_LOOK = re.compile(
    r"\b(action required|escalat\w*|payment|overdue|past due|due (on|by|date|soon)"
    r"|expir(es|ing|ed|y)|deadline"
    r"|security|suspicious|unauthori[sz]ed|sign-?in|password|declined|invoice|interview"
    r"|offer letter|your application|verify your|final notice|renewal|outage|cancell?ed)\b",
    re.I,
)


# The folder for mail tools send. The AI skips it; the Sort step files tools under it.
AUTOMATED = "Automated"

# Used for grouping history, never for literal Exact prefix matching.
REPLY_PREFIX = re.compile(r"^(?:\s*(?:re|fwd?|aw)\s*:\s*)+", re.I)


@dataclass(frozen=True)
class RuleMatch:
    name: str
    actions: RuleActions
    # Only a guess from its headers, so what it says can still bring it to the agent.
    look_closer: bool = False
    extra_categories: tuple[str, ...] = ()

    @property
    def why(self) -> str:
        return f"Matched the rule “{self.name}”"


_WRITING = threading.Lock()


# Their names, because they only guess from headers, unlike a rule the person wrote.
BUILT_IN_RULES = frozenset(
    {
        "Notification from a system",
        "Automatically generated mail",
        "From a social network",
        "Company bulk mail",
        "Marketing or bulk mail",
        "Mailing list",
        "Sent from a no-reply address",
    }
)


def _builtin(parsed: ParsedMessage, own_domain: str | None = None) -> RuleMatch | None:
    """Mail headers say what kind of mail this is, with no model and no tokens, on any server."""
    headers = parsed.headers
    # Whatever its headers say it is, mail a tool sends goes to the one folder the AI skips.
    updates = promotions = forums = RuleActions(category=AUTOMATED, skip_agent=True)
    sender_domain = parsed.from_addr.rpartition("@")[2].lower()
    internal = bool(own_domain) and sender_domain == own_domain
    if any(header in headers for header in SYSTEM_NOTICE_HEADERS):
        return RuleMatch("Notification from a system", updates)
    auto_submitted = headers.get("auto-submitted", "no").lower()
    if not auto_submitted.startswith("no") or "x-auto-response-suppress" in headers:
        return RuleMatch("Automatically generated mail", updates, True)
    # A company's own server has no social mail to speak of, and nor is its own mail a promotion.
    if not own_domain and any(
        sender_domain == domain or sender_domain.endswith(f".{domain}") for domain in SOCIAL_DOMAINS
    ):
        return RuleMatch("From a social network", forums)
    precedence = headers.get("precedence", "").lower()
    if "list-unsubscribe" in headers or precedence in {"bulk", "junk"}:
        if internal:
            return RuleMatch("Company bulk mail", updates)
        return RuleMatch("Marketing or bulk mail", promotions)
    if "list-id" in headers or precedence == "list":
        return RuleMatch("Mailing list", forums)
    if NO_REPLY.search(parsed.from_addr):
        return RuleMatch("Sent from a no-reply address", updates, True)
    return None


def _condition_matches(condition: RuleCondition, parsed: ParsedMessage) -> bool:
    needle = condition.value.lower()
    if condition.field == "subject":
        return needle in parsed.subject.lower()
    if condition.field == "subject_prefix":
        return parsed.subject.lower().startswith(needle)
    if condition.field == "tag":
        return needle.casefold() in {tag.casefold() for tag in tags_of(parsed.subject)}
    if condition.field == "body":
        return needle in parsed.text.lower()
    if condition.field == "sender_exact":
        return needle == parsed.from_addr.lower()
    if condition.field == "sender":
        return needle in f"{parsed.from_name} {parsed.from_addr}".lower()
    if condition.field == "header":
        return needle in parsed.headers.get((condition.header or "").lower(), "").lower()
    return any(part.disposition == "attachment" for part in parsed.parts)


def own_domain_of(address: str) -> str | None:
    """The company's domain. Mail services like Gmail have no such thing."""
    domain = address.rpartition("@")[2].lower()
    return None if not domain or domain in PUBLIC_MAIL_DOMAINS else domain


def evaluate(
    parsed: ParsedMessage,
    rules: list[MailRule],
    own_domain: str | None = None,
    folder_modes: Mapping[str, str] | None = None,
) -> RuleMatch | None:
    """The person's own rules come first, because they know their mail best."""
    matched = [
        rule
        for rule in rules
        if rule.enabled
        and all(_condition_matches(condition, parsed) for condition in rule.conditions)
    ]
    if matched:
        first = matched[0]
        extras = tuple(
            dict.fromkeys(
                rule.actions.category
                for rule in matched[1:]
                if rule.actions.category and rule.actions.category != first.actions.category
            )
        )
        return RuleMatch(first.name, first.actions, extra_categories=extras)
    match = _builtin(parsed, own_domain)
    if (
        match
        and folder_modes is not None
        and folder_modes.get(match.actions.category or "") != "exact"
    ):
        return None
    return match


@dataclass(frozen=True)
class Decision:
    """What the rule engine decided for one email: whether the AI reads it, and why."""

    reaches_ai: bool
    why: str
    # The rule that matched, if one did. It files the mail even when the AI still reads it.
    match: RuleMatch | None = None
    # Why it reaches the AI although its rule keeps mail away: the rule's own exception.
    exception: str = ""

    @property
    def rule(self) -> str | None:
        return self.match.name if self.match else None

    @property
    def category(self) -> str | None:
        return self.match.actions.category if self.match else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reaches_ai": self.reaches_ai,
            "why": self.why,
            "rule": self.rule,
            "category": self.category,
            "exception": self.exception,
        }


def is_reply(parsed: ParsedMessage) -> bool:
    """Part of a conversation: a Re: or Fwd: subject, or an answer to earlier mail."""
    return bool(SUBJECT_PREFIX.match(parsed.subject) or parsed.in_reply_to)


def _names_them(actions: RuleActions, parsed: ParsedMessage) -> bool:
    if not actions.mentions:
        return False
    owner, *name = actions.mentions
    names = grouping._mention(owner, name[0] if name else "")
    return grouping._addressed(names, parsed.subject, parsed.own)


@dataclass(frozen=True)
class Engine:
    """Every email goes through here before the AI sees it. A batch goes in, and one decision per
    email comes out in the same order. Switched off, it decides nothing: every email reaches the
    AI and nothing is filed."""

    rules: Sequence[MailRule]
    own_domain: str | None = None
    folder_modes: Mapping[str, str] | None = None
    on: bool = True

    def match(self, parsed: ParsedMessage) -> RuleMatch | None:
        if not self.on:
            return None
        return evaluate(parsed, list(self.rules), self.own_domain, self.folder_modes)

    def decide(self, emails: Sequence[ParsedMessage]) -> list[Decision]:
        return [self._decide(parsed) for parsed in emails]

    def _decide(self, parsed: ParsedMessage) -> Decision:
        if not self.on:
            return Decision(True, "Rules are off, so the AI reads everything")
        return decision_for(self.match(parsed), parsed)


def decision_for(match: RuleMatch | None, parsed: ParsedMessage) -> Decision:
    """What a matched rule means for the AI, with its exceptions: mail that names the person,
    a reply where its rule lets replies through, and a guessed kind whose subject could matter."""
    if match is None:
        return Decision(True, "No rule matched")
    if not match.actions.skip_agent:
        return Decision(True, f"Filed by “{match.name}”, which lets the AI read it", match)
    if _names_them(match.actions, parsed):
        return Decision(True, match.why, match, "It names you")
    if match.actions.read_replies and is_reply(parsed):
        return Decision(True, match.why, match, "A reply: a person joined in")
    if match.look_closer and WORTH_A_LOOK.search(parsed.subject):
        return Decision(True, match.why, match, "Its subject could matter to you")
    return Decision(False, f"Kept from the AI by “{match.name}”", match)


FIELD_WORDS = {
    "subject": "the subject has “{}”",
    "subject_prefix": "the subject starts with “{}”",
    "tag": "the subject carries the tag [{}]",
    "body": "the text has “{}”",
    "sender": "the sender has “{}”",
    "sender_exact": "it's from {}",
}


def describe_rule(rule: MailRule) -> str:
    """A rule in plain words: "If it's from a@x and the subject carries the tag [PLM] → file in
    Automated/PLM, the AI skips it, except replies and mail that names you"."""
    said = []
    for condition in rule.conditions:
        if condition.field == "header":
            said.append(f"the header {condition.header} has “{condition.value}”")
        elif condition.field == "has_attachment":
            said.append("it has an attachment")
        else:
            said.append(FIELD_WORDS[condition.field].format(condition.value))
    actions = rule.actions
    then = [f"file in {actions.category}"] if actions.category else []
    if actions.skip_agent:
        then.append("the AI skips it")
    if actions.mark_read:
        then.append("mark it read")
    if actions.notify:
        then.append("tell you")
    excepted = [
        *(["replies"] if actions.skip_agent and actions.read_replies else []),
        *(["mail that names you"] if actions.skip_agent and actions.mentions else []),
    ]
    text = f"If {' and '.join(said)} → {', '.join(then) or 'do nothing'}"
    return text + (f", except {' and '.join(excepted)}" if excepted else "")


def rules_path(home: Path) -> Path:
    return home / "system" / "rules.json"


def load_rules(home: Path) -> list[MailRule]:
    path = rules_path(home)
    if not path.exists():
        return []
    return RuleSet.model_validate(json.loads(path.read_text(encoding="utf-8"))).rules


def save_rules(home: Path, rules: RuleSet) -> None:
    with _WRITING:
        _write(home, rules)


def _write(home: Path, rules: RuleSet) -> None:
    path = rules_path(home)
    # Its own name each time, so two saves at once can't take each other's file away.
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(rules.model_dump_json(indent=2), encoding="utf-8")
    replace_file(temporary, path)


def change_rules(home: Path, change: Callable[[list[MailRule]], list[MailRule]]) -> None:
    """Reads and writes as one step, so tools running side by side can't lose each other's rule."""
    with _WRITING:
        _write(home, RuleSet(rules=change(load_rules(home))))


def for_folders(rules: list[MailRule], folders: list[Any], starters: set[str]) -> list[MailRule]:
    """Personal rules precede starter/header rules; folder ties follow sidebar position."""
    settings = {row["name"]: row for row in folders}
    indexed = []
    for index, rule in enumerate(rules):
        category = rule.actions.category
        folder = settings.get(category)
        if folder is not None and folder["mode"] == "smart":
            continue
        if folder is not None:
            rule = rule.model_copy(
                update={
                    "actions": rule.actions.model_copy(
                        update={"skip_agent": True, "read_replies": False}
                    )
                }
            )
        indexed.append(
            (
                category in starters,
                (folder["position"] or 1_000_000) if folder else index,
                index,
                rule,
            )
        )
    return [item[3] for item in sorted(indexed, key=lambda item: item[:3])]
