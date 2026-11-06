"""Fixed rules that run before any model, so routine mail costs nothing to handle."""

import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition, RuleSet
from nexusai.kernel.files import replace_file
from nexusai.modules.mail.parse import ParsedMessage

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


# Automated mail goes unjudged, unless what it says could cost the person something.
WORTH_A_LOOK = re.compile(
    r"\b(action required|escalat\w*|payment|overdue|past due|due (on|by|date|soon)"
    r"|expir(es|ing|ed|y)|deadline"
    r"|security|suspicious|unauthori[sz]ed|sign-?in|password|declined|invoice|interview"
    r"|offer letter|your application|verify your|final notice|renewal|outage|cancell?ed)\b",
    re.I,
)


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
    updates = RuleActions(category="Updates", skip_agent=True)
    promotions = RuleActions(category="Promotions", skip_agent=True)
    forums = RuleActions(category="Forums", skip_agent=True)
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
        return RuleMatch("From a social network", RuleActions(category="Social", skip_agent=True))
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
