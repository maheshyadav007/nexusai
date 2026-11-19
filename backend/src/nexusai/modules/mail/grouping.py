"""Finds mail that tools send, from the mail alone, so it can be kept away from the AI.

Nothing here names a sender, a tag, a team or a language's phrases. A tool sends the same few
subjects again and again, with the same ending, and nobody writes back in its threads; people write
a new subject each time and answer each other. Everything below measures that, per sender, and the
person names and confirms the groups.
"""

import json
import re
import sys
import zlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from email import message_from_bytes, policy
from email.utils import getaddresses
from pathlib import Path
from typing import Literal

from nexusai.kernel import vault
from nexusai.kernel.database import connect_raw
from nexusai.kernel.secrets import secret_store
from nexusai.modules.mail.parse import ParsedMessage, normalize_subject, parse_message

Section = Literal["automated", "calendar", "people", "too_few"]
SMART: dict[Section, bool] = {
    "automated": False,
    "calendar": False,
    "people": True,
    "too_few": True,
}
# A subject seen this often from one sender is a template, not something typed again.
REPEATS = 3
# Fewer emails than this give no pattern to go by, unless the headers say outright it's bulk mail.
ENOUGH = 20
# A sender's mail counts as having a trait when this share of it does.
MOSTLY = 0.75
# Outlook's conversation mark only tells people from tools where most people's mail carries it.
MARKED_MAILBOX = 0.2
# Mentions mean nothing in a group that names the person in most of its mail, like a team report.
NAMES_EVERYONE = 0.5
TAGS = re.compile(r"^\s*(\[[^\]]{1,40}\])")
HAS_DIGIT = re.compile(r"\S*\d\S*")
FIRST_TAG = re.compile(r"^\s*(?:(?:re|fwd?|aw|sv)\s*:\s*)*\[([^\]]{1,40})\]", re.IGNORECASE)
BULK_PRECEDENCE = {"bulk", "list", "junk"}


@dataclass
class Mail:
    key: str
    parsed: ParsedMessage
    sender: str
    pattern: str
    repeat_key: str
    ending: str
    calendar: str | None
    marked: bool
    bulk: bool
    named: bool
    thread: str = ""


@dataclass
class Group:
    id: str
    section: Section
    # A starting name for the person to change; empty when many people send the group.
    label: str
    senders: list[str]
    count: int
    subjects: int
    patterns: list[tuple[str, int]]
    samples: list[str]
    reasons: list[str]
    mentions: int
    mentions_ignored: bool
    smart: bool
    members: list[str] = field(repr=False)


@dataclass
class Decision:
    group: str | None
    section: Section
    smart: bool
    reaches_ai: bool
    named: bool


@dataclass
class Report:
    owner: str
    owner_name: str
    groups: list[Group]
    decisions: dict[str, Decision]


def pattern_of(subject: str) -> tuple[str, str]:
    """The subject with numbers taken out, and what repeats: its first tag when it has one."""
    rest = normalize_subject(subject)
    tags: list[str] = []
    while match := TAGS.match(rest):
        tags.append(re.sub(r"\d+", "#", match.group(1)))
        rest = rest[match.end() :]
    body = HAS_DIGIT.sub("#", rest).strip()
    pattern = " ".join([*tags, body]).strip()
    return pattern, tags[0] if tags else pattern


def _ending(text: str) -> str:
    lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return HAS_DIGIT.sub("#", " / ".join(lines[-2:]))


def _calendar(raw: bytes, parsed: ParsedMessage) -> str | None:
    """ "request" or "response" for calendar mail, from its calendar part or Outlook's mark."""
    marked = "calendarmessage" in parsed.headers.get("content-class", "").lower()
    if not marked and not any(part.content_type == "text/calendar" for part in parsed.parts):
        return None
    message = message_from_bytes(raw, policy=policy.default)
    for part in message.walk():
        if part.get_content_type() == "text/calendar":
            payload = part.get_payload(decode=True)
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else ""
            found = re.search(r"^METHOD:(\w+)", text, re.MULTILINE | re.IGNORECASE)
            if found and found.group(1).upper() == "REPLY":
                return "response"
            return "request"
    return "response"


def _bulk(headers: dict[str, str]) -> bool:
    return (
        "list-unsubscribe" in headers
        or "list-id" in headers
        or headers.get("precedence", "").strip().lower() in BULK_PRECEDENCE
        or not headers.get("auto-submitted", "no").strip().lower().startswith("no")
    )


def _owner(parsed: list[ParsedMessage]) -> tuple[str, str]:
    """Whose mailbox this is: the address most mail is sent to, and the name it goes by."""
    counts = Counter(address for item in parsed for address in {*item.to, *item.cc})
    if not counts:
        return "", ""
    owner = counts.most_common(1)[0][0]
    names = Counter(
        name.strip()
        for item in parsed
        for name, address in getaddresses([item.headers.get("to", ""), item.headers.get("cc", "")])
        if address.lower() == owner and name.strip() and "@" not in name
    )
    if names:
        return owner, names.most_common(1)[0][0]
    return owner, " ".join(re.split(r"[._-]+", owner.split("@")[0])).strip().title()


def _mention(owner: str, name: str) -> re.Pattern[str]:
    local = owner.split("@")[0]
    words = [re.escape(word) for word in name.split() if word]
    choices = [re.escape(owner), rf"(?<![\w.]){re.escape(local)}(?![\w])"]
    if len(words) >= 2:
        choices.append(r"\b" + r"[\s.]+".join(words) + r"\b")
    return re.compile("|".join(choices), re.IGNORECASE)


class _Threads:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def join(self, first: str, second: str) -> None:
        self.parent[self.find(first)] = self.find(second)


def _stem(sender: str) -> str:
    """alerts@ and alerts-eu2@ share a stem: the letters before the first other character."""
    local, _, domain = sender.partition("@")
    first = re.split(r"[^a-z]+", local.lower())
    return f"{first[0] if first and first[0] else local}@{domain}"


def _first_tag(subject: str) -> str:
    """The first [tag] as the sender typed it, without numbers: "[RND-1104] ..." gives "RND"."""
    found = FIRST_TAG.match(subject)
    if not found:
        return ""
    return re.sub(r"[\s#:_-]*\d[\w-]*", "", found.group(1)).strip(" -_:#")


def _site(domain: str) -> str:
    """The name a domain is registered under: mail.vendor.com and vendor.co.uk give vendor."""
    labels = domain.split(".")[:-1]
    while len(labels) > 1 and len(labels[-1]) <= 3:
        labels.pop()
    return labels[-1] if labels else domain


def _label(items: list[Mail], own_domain: str) -> str:
    """A name the person can change, by a fixed rule: the first tag most emails start with, else
    the sender (its address before the @ inside the company, its domain outside), else nothing
    when many people send the group."""
    tags = Counter(_first_tag(item.parsed.subject) for item in items)
    tag, count = tags.most_common(1)[0]
    if tag and count / len(items) >= MOSTLY:
        return tag
    senders = sorted({item.sender for item in items})
    domains = {sender.partition("@")[2] for sender in senders}
    if len(domains) == 1 and (domain := next(iter(domains))) != own_domain:
        return _site(domain)
    if len(senders) == 1:
        return senders[0].partition("@")[0]
    stem = _stem(senders[0])
    if all(_stem(sender) == stem for sender in senders):
        return stem.partition("@")[0]
    return ""


def _share(items: list[Mail], test: Callable[[Mail], bool]) -> float:
    return sum(1 for item in items if test(item)) / len(items) if items else 0.0


def group_mailbox(raws: Iterable[tuple[str, bytes]]) -> Report:
    loaded = [(key, raw, parse_message(raw)) for key, raw in raws]
    owner, owner_name = _owner([parsed for _, _, parsed in loaded])
    own_domain = owner.partition("@")[2]
    mention = _mention(owner, owner_name) if owner else None
    mails: list[Mail] = []
    for key, raw, parsed in loaded:
        pattern, repeat_key = pattern_of(parsed.subject)
        mails.append(
            Mail(
                key=key,
                parsed=parsed,
                sender=parsed.from_addr,
                pattern=pattern,
                repeat_key=repeat_key,
                ending=_ending(parsed.text),
                calendar=_calendar(raw, parsed),
                marked="thread-index" in parsed.headers,
                bulk=_bulk(parsed.headers),
                named=bool(mention and mention.search(f"{parsed.subject}\n{parsed.own}")),
            )
        )

    threads = _Threads()
    by_id = {mail.parsed.message_id: mail for mail in mails}
    for mail in mails:
        threads.find(mail.parsed.message_id)
        for ref in [mail.parsed.in_reply_to, *mail.parsed.references]:
            if ref:
                threads.join(mail.parsed.message_id, ref)
        if mail.parsed.thread_index_root:
            threads.join(mail.parsed.message_id, f"ti:{mail.parsed.thread_index_root}")
    writers: dict[str, set[str]] = defaultdict(set)
    for mail in mails:
        mail.thread = threads.find(mail.parsed.message_id)
        writers[mail.thread].add(mail.sender)
    marks_usable = _share(mails, lambda m: m.marked) >= MARKED_MAILBOX

    def answers_people(sender: str, items: list[Mail]) -> bool:
        """A tool never replies to someone else's message; people do."""
        for item in items:
            parent = by_id.get(item.parsed.in_reply_to or "")
            if parent is not None and parent.sender != sender:
                return True
        return False

    def evidence(items: list[Mail]) -> list[str]:
        reasons: list[str] = []
        if marks_usable and _share(items, lambda m: not m.marked) >= MOSTLY:
            reasons.append("Sent by an app, not a mail program")
        if _share(items, lambda m: m.bulk) >= MOSTLY:
            reasons.append("Its headers mark it as bulk or automatic")
        endings = Counter(item.ending for item in items)
        same_ending = bool(endings) and endings.most_common(1)[0][1] / len(items) >= MOSTLY
        alone = _share(items, lambda m: writers[m.thread] == {m.sender}) >= MOSTLY
        if same_ending and alone:
            reasons.append("Every email ends the same way, and nobody writes back")
        return reasons

    groups: list[Group] = []
    decided: dict[str, tuple[str | None, Section]] = {}

    def add(section: Section, gid: str, items: list[Mail], reasons: list[str]) -> None:
        patterns = Counter(item.pattern for item in items)
        named = sum(item.named for item in items)
        groups.append(
            Group(
                id=gid,
                section=section,
                label=_label(items, own_domain),
                senders=sorted({item.sender for item in items}),
                count=len(items),
                subjects=len(patterns),
                patterns=patterns.most_common(3),
                samples=[item.parsed.subject for item in items[:3]],
                reasons=reasons,
                mentions=named,
                mentions_ignored=bool(items) and named / len(items) > NAMES_EVERYONE,
                smart=SMART[section],
                members=[item.key for item in items],
            )
        )
        for item in items:
            decided[item.key] = (gid, section)

    calendar = [mail for mail in mails if mail.calendar]
    for kind in ("request", "response"):
        items = [mail for mail in calendar if mail.calendar == kind]
        if items:
            reason = (
                "Carries a calendar request" if kind == "request" else "Answers a calendar request"
            )
            add("calendar", f"calendar:{kind}", items, [reason])

    by_sender: dict[str, list[Mail]] = defaultdict(list)
    for mail in mails:
        if not mail.calendar:
            by_sender[mail.sender].append(mail)
    machine: dict[str, list[Mail]] = defaultdict(list)
    machine_reasons: dict[str, list[str]] = defaultdict(list)
    for sender, items in by_sender.items():
        if answers_people(sender, items):
            continue
        external = sender.partition("@")[2] != own_domain
        if external and _share(items, lambda m: m.bulk) >= MOSTLY:
            chosen, reasons = items, ["Bulk mail from outside the company"]
        else:
            keys = Counter(item.repeat_key for item in items)
            repeated = [item for item in items if keys[item.repeat_key] >= REPEATS]
            unmarked = [item for item in items if not item.marked] if marks_usable else []
            # Repeated subjects, or failing that, mail no person's program sent that looks alike.
            candidates: list[tuple[list[Mail], list[str]]] = []
            if repeated and (found := evidence(repeated)):
                candidates.append((repeated, ["The same few subjects again and again", *found]))
            if len(unmarked) >= ENOUGH and len(found_unmarked := evidence(unmarked)) >= 2:
                candidates.append((unmarked, found_unmarked))
            chosen, reasons = max(candidates, key=lambda c: len(c[0]), default=([], []))
            # A sender that is a tool for nearly all its mail is a tool for the rest too.
            if chosen and len(chosen) / len(items) >= MOSTLY:
                chosen = items
            if chosen and len(chosen) < ENOUGH and not any("bulk" in r for r in reasons):
                # Mail from a person's program needs a real pattern before anyone calls it a tool.
                if not (marks_usable and _share(chosen, lambda m: m.marked) >= MOSTLY):
                    add("too_few", f"few:{sender}", chosen, ["Too few emails to be sure", *reasons])
                continue
        if chosen:
            stem = _stem(sender)
            machine[stem].extend(chosen)
            machine_reasons[stem] = list(dict.fromkeys([*machine_reasons[stem], *reasons]))
    for stem, items in machine.items():
        add("automated", f"auto:{stem}", items, machine_reasons[stem])

    # People writing to many: a sender whose mail mostly reaches the person through a list.
    for sender, items in by_sender.items():
        rest = [item for item in items if item.key not in decided]
        via_list = [item for item in rest if owner not in {*item.parsed.to, *item.parsed.cc}]
        if len(via_list) >= 5 and len(via_list) / len(rest) >= MOSTLY:
            add("people", f"many:{sender}", via_list, ["Written by a person, sent to a list"])

    ignored = {group.id for group in groups if group.mentions_ignored}
    decisions: dict[str, Decision] = {}
    for mail in mails:
        fallback: tuple[str | None, Section] = (None, "people")
        gid, section = decided.get(mail.key, fallback)
        smart = SMART[section]
        named = mail.named and gid not in ignored
        decisions[mail.key] = Decision(gid, section, smart, smart or named, mail.named)
    groups.sort(key=lambda group: (list(SMART).index(group.section), -group.count))
    return Report(owner, owner_name, groups, decisions)


def read_folder(folder: Path) -> list[tuple[str, bytes]]:
    return [(path.name, path.read_bytes()) for path in sorted(folder.glob("*.eml"))]


def read_home(home: Path, account: str | None = None) -> list[tuple[str, bytes]]:
    """Every kept email of one account in a Home, opened read-only. It never creates a key,
    so a Home without one is refused rather than changed."""
    sealed = vault._read(home)
    key = secret_store(None).get(vault._key_name(sealed["id"])) if sealed else None
    if key is None:
        raise SystemExit("This Home's key isn't on this computer, so it can't be read.")
    database = home / "system" / "nexusai.db"
    connection = connect_raw(Path(f"file:{database}?mode=ro"), key, uri=True)
    try:
        accounts = connection.execute(
            "SELECT account, COUNT(*) AS n FROM messages GROUP BY account ORDER BY n DESC"
        ).fetchall()
        chosen = account or (accounts[0][0] if accounts else "")
        rows = connection.execute(
            "SELECT m.id, r.data FROM messages m JOIN message_raw r ON r.message = m.id"
            " WHERE m.account = ? AND m.folder_role NOT IN ('junk', 'trash') ORDER BY m.id",
            (chosen,),
        ).fetchall()
    finally:
        connection.close()
    return [(str(row[0]), zlib.decompress(row[1])) for row in rows]


def describe(report: Report) -> str:
    total = len(report.decisions)
    kept = sum(1 for d in report.decisions.values() if not d.reaches_ai)
    lines = [
        f"Mailbox of {report.owner_name} <{report.owner}>: {total} emails, "
        f"{kept} kept away from the AI, {total - kept} reach it.",
        "",
    ]
    for group in report.groups:
        mentions = f", names you in {group.mentions}" if group.mentions else ""
        if group.mentions_ignored:
            mentions += " (ignored: names everyone)"
        senders = ", ".join(group.senders[:3]) + (" …" if len(group.senders) > 3 else "")
        lines.append(
            f"[{group.section}] {senders}: "
            f"{group.count} emails, {group.subjects} different subjects{mentions}"
        )
        lines.append(f"    why: {'; '.join(group.reasons)}")
        for pattern, count in group.patterns:
            lines.append(f"    {count:>5}  {pattern}")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    """The groups and totals a page needs, without each email's own decision."""
    grouped = {key for group in report.groups for key in group.members}
    return json.dumps(
        {
            "owner": report.owner,
            "owner_name": report.owner_name,
            "total": len(report.decisions),
            "ungrouped": sum(1 for key in report.decisions if key not in grouped),
            "groups": [
                {k: v for k, v in asdict(group).items() if k != "members"}
                for group in report.groups
            ],
        },
        indent=1,
    )


if __name__ == "__main__":
    # A folder of .eml files, or --home PATH [--account ADDRESS] for a Home's stored mail.
    arguments = [a for a in sys.argv[1:] if a != "--json"]
    if arguments and arguments[0] == "--home":
        chosen = arguments[arguments.index("--account") + 1] if "--account" in arguments else None
        mail = read_home(Path(arguments[1]), chosen)
    else:
        mail = read_folder(Path(arguments[0]))
    found = group_mailbox(mail)
    print(to_json(found) if "--json" in sys.argv else describe(found))
