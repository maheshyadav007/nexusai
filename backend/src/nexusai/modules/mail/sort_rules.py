"""The rules a sorted category gets for mail still to come, written the same way for the app and the
Sort lab: one per sender, or one per way its subjects start when most of its mail starts the same
few ways, and one for the subject tag the category's mail carries, when that tag belongs to it.
Nothing here names a tool, a tag or a subject; all come from the mailbox.

Only the contracts, the parser and the rule engine, so the Sort lab can use it without the
database or the keychain.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import takewhile

from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition
from nexusai.modules.mail.parse import SUBJECT_PREFIX, ParsedMessage, tags_of
from nexusai.modules.mail.rules import is_reply

PREFIX = "Sorted: "
# A rule the person asked for, so a sender's mail reaches the AI whatever else would match it.
READS_PREFIX = "AI reads: "
# A tag names a category when this share of the category's mail carries it, and this share of
# all the mail carrying it is the category's. A tag every tool uses, like [Reminder], fails that.
MOSTLY = 0.75
# One email can't show that a tag repeats.
AT_LEAST = 2
# How a subject starts: its first few words, up to the first number, which changes each time.
START_WORDS = 3
# A sender's mail is told apart by how its subjects start when this many ways cover most of it.
MOST_STARTS = 3
UP_TO_NUMBER = re.compile(r"\d")
LEADING_TAGS = re.compile(r"^\s*(\[[^\[\]]*\]\s*)+")
# Punctuation around a word isn't part of what's written each time: "Invoice:" is "invoice".
EDGES = "\"'“”‘’.,:;!?#-_()|/"


@dataclass(frozen=True)
class Seen:
    """What the rules are written from: who sent an email, its subject, and whether it answers
    someone. The app reads these from its database; the lab from the mail itself."""

    sender: str
    subject: str
    reply: bool

    @classmethod
    def of(cls, parsed: ParsedMessage) -> "Seen":
        return cls(parsed.from_addr, parsed.subject, is_reply(parsed))


def own_tag(senders: Iterable[str], mailbox: Sequence[Seen]) -> str:
    """The tag that marks these senders' mail and little else, as most of it spells it, or ""."""
    chosen = set(senders)
    started = [seen for seen in mailbox if not seen.reply]
    mine = [seen for seen in started if seen.sender in chosen]
    if len(mine) < AT_LEAST:
        return ""
    counts = Counter(tag.casefold() for seen in mine for tag in tags_of(seen.subject))
    for tag, count in counts.most_common():
        if count / len(mine) < MOSTLY:
            break
        carrying = [
            seen for seen in started if tag in {t.casefold() for t in tags_of(seen.subject)}
        ]
        if sum(seen.sender in chosen for seen in carrying) / len(carrying) >= MOSTLY:
            spelled = Counter(
                t for seen in mine for t in tags_of(seen.subject) if t.casefold() == tag
            )
            return spelled.most_common(1)[0][0]
    return ""


def start_of(subject: str) -> str:
    """The first words of a subject, after any Re: or [tag] and before any number, or "" when
    that's too little to go on: "[HR] Your OTP for login is 4821" starts "your otp for"."""
    rest = LEADING_TAGS.sub("", SUBJECT_PREFIX.sub("", subject or ""))
    head = UP_TO_NUMBER.split(" ".join(rest.lower().split()), maxsplit=1)[0]
    words = [word.strip(EDGES) for word in head.split()[:START_WORDS]]
    kept = list(takewhile(bool, words))
    return " ".join(kept) if len(kept) >= AT_LEAST else ""


def subject_starts(subjects: Sequence[str]) -> list[str]:
    """The few ways a sender's subjects start, when they cover most of its mail; else none, and
    the sender's rule takes all of it. Each way is seen at least twice."""
    if len(subjects) < AT_LEAST:
        return []
    counts = Counter(start_of(subject) for subject in subjects)
    counts.pop("", None)
    common = [
        (start, count) for start, count in counts.most_common(MOST_STARTS) if count >= AT_LEAST
    ]
    if sum(count for _, count in common) / len(subjects) < MOSTLY:
        return []
    return sorted(start for start, _ in common)


def rules_for(
    category: str,
    senders: Iterable[str],
    mailbox: Sequence[Seen],
    owner: str = "",
    starts: Mapping[str, Sequence[str]] | None = None,
) -> list[MailRule]:
    """Rules that file what's to come under `category` and keep it from the AI. A sender with
    `starts`, the few ways its subjects start as scoring found them, gets a rule for each, so
    something new from it still reaches the AI; any other sender, one rule for all its mail."""
    chosen = sorted({sender for sender in senders if sender and sender != owner})
    found = []
    for sender in chosen:
        ways = (starts or {}).get(sender, [])
        for start in ways:
            found.append(
                MailRule(
                    name=f"{PREFIX}{category}: {sender} · {start}"[:120],
                    conditions=[
                        RuleCondition(field="sender_exact", value=sender),
                        RuleCondition(field="subject", value=start),
                    ],
                    actions=RuleActions(category=category, skip_agent=True),
                )
            )
        if not ways:
            found.append(
                MailRule(
                    name=f"{PREFIX}{category}: {sender}"[:120],
                    conditions=[RuleCondition(field="sender_exact", value=sender)],
                    actions=RuleActions(category=category, skip_agent=True),
                )
            )
    if tag := own_tag(chosen, mailbox):
        found.append(
            MailRule(
                name=f"{PREFIX}{category}: [{tag}]"[:120],
                conditions=[RuleCondition(field="tag", value=tag)],
                actions=RuleActions(category=category, skip_agent=True),
            )
        )
    return found
