"""Fixed rules that run before any model, so routine mail costs nothing to handle."""

import json
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition, RuleSet
from nexusai.modules.mail.parse import ParsedMessage

NO_REPLY = re.compile(
    r"(^|[._+-])(no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?)@", re.I
)


@dataclass(frozen=True)
class RuleMatch:
    name: str
    actions: RuleActions

    @property
    def why(self) -> str:
        return f"Matched the rule “{self.name}”"


_WRITING = threading.Lock()


def _builtin(parsed: ParsedMessage) -> RuleMatch | None:
    headers = parsed.headers
    automated = RuleActions(category="Automated", skip_agent=True)
    auto_submitted = headers.get("auto-submitted", "no").lower()
    if not auto_submitted.startswith("no") or "x-auto-response-suppress" in headers:
        return RuleMatch("Automatically generated mail", automated)
    if "list-id" in headers or "list-unsubscribe" in headers:
        newsletter = RuleActions(category="Newsletters", skip_agent=True)
        return RuleMatch("Mailing list or newsletter", newsletter)
    if headers.get("precedence", "").lower() in {"bulk", "list", "junk"}:
        return RuleMatch("Bulk mail", RuleActions(category="Newsletters", skip_agent=True))
    if NO_REPLY.search(parsed.from_addr):
        return RuleMatch("Sent from a no-reply address", automated)
    return None


def _condition_matches(condition: RuleCondition, parsed: ParsedMessage) -> bool:
    needle = condition.value.lower()
    if condition.field == "subject":
        return needle in parsed.subject.lower()
    if condition.field == "body":
        return needle in parsed.text.lower()
    if condition.field == "sender":
        return needle in f"{parsed.from_name} {parsed.from_addr}".lower()
    if condition.field == "header":
        return needle in parsed.headers.get((condition.header or "").lower(), "").lower()
    return any(part.disposition == "attachment" for part in parsed.parts)


def evaluate(parsed: ParsedMessage, rules: list[MailRule]) -> RuleMatch | None:
    """The person's own rules come first, because they know their mail best."""
    for rule in rules:
        if rule.enabled and all(_condition_matches(c, parsed) for c in rule.conditions):
            return RuleMatch(rule.name, rule.actions)
    return _builtin(parsed)


def rules_path(home: Path) -> Path:
    return home / "system" / "rules.json"


def load_rules(home: Path) -> list[MailRule]:
    path = rules_path(home)
    if not path.exists():
        return []
    return RuleSet.model_validate(json.loads(path.read_text())).rules


def save_rules(home: Path, rules: RuleSet) -> None:
    with _WRITING:
        _write(home, rules)


def _write(home: Path, rules: RuleSet) -> None:
    path = rules_path(home)
    # Its own name each time, so two saves at once can't take each other's file away.
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(rules.model_dump_json(indent=2))
    temporary.replace(path)


def change_rules(home: Path, change: Callable[[list[MailRule]], list[MailRule]]) -> None:
    """Reads and writes as one step, so tools running side by side can't lose each other's rule."""
    with _WRITING:
        _write(home, RuleSet(rules=change(load_rules(home))))
