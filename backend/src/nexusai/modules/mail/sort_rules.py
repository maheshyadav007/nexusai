"""The rules a sorted category gets for mail still to come, written the same way for the app and the
Sort lab: one per sender, and one for the subject tag the category's mail carries, when that tag
belongs to it. Nothing here names a tool or a tag; both come from the mailbox.

Only the contracts, the parser and the rule engine, so the Sort lab can use it without the
database or the keychain.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from nexusai.contracts.mail import MailRule, RuleActions, RuleCondition
from nexusai.modules.mail.parse import ParsedMessage, tags_of
from nexusai.modules.mail.rules import is_reply

PREFIX = "Sorted: "
# A tag names a category when this share of the category's mail carries it, and this share of
# all the mail carrying it is the category's. A tag every tool uses, like [Reminder], fails that.
MOSTLY = 0.75
# One email can't show that a tag repeats.
AT_LEAST = 2


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


def rules_for(
    category: str,
    senders: Iterable[str],
    mailbox: Sequence[Seen],
    mentions: Sequence[str] = (),
    owner: str = "",
) -> list[MailRule]:
    """Rules that file what's to come under `category` and keep it from the AI, unless it names
    the person. A tool's own address never writes to anyone, so its rule needs no exception for
    replies; a tag can also turn up in a person's reply, so the tag's rule lets replies through."""
    chosen = sorted({sender for sender in senders if sender and sender != owner})
    named = [who for who in mentions if who][:4]
    found = []
    for sender in chosen:
        found.append(
            MailRule(
                name=f"{PREFIX}{category}: {sender}"[:120],
                conditions=[RuleCondition(field="sender_exact", value=sender)],
                actions=RuleActions(category=category, skip_agent=True, mentions=named),
            )
        )
    if tag := own_tag(chosen, mailbox):
        found.append(
            MailRule(
                name=f"{PREFIX}{category}: [{tag}]"[:120],
                conditions=[RuleCondition(field="tag", value=tag)],
                actions=RuleActions(
                    category=category, skip_agent=True, read_replies=True, mentions=named
                ),
            )
        )
    return found
