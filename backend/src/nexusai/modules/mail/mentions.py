"""Whether a person replying on mail the AI doesn't read named the person: "@Mahesh please check
the BOM" on a PLM thread. Tools greet everyone by name, so "Dear Mahesh Yadav" in a tool's own
mail never counts; only what a person wrote in a reply or forward does, without the quoted mail
below it or their signature. A tool passing on a person's mention ("Rahul mentioned you") counts
too.

Who the person is lives in one small object they can change: their names, addresses and ids,
and the other people whose names look like theirs.
"""

import json
import re
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from nexusai.contracts.mail import MailMe
from nexusai.kernel.files import replace_file
from nexusai.modules.mail.parse import SUBJECT_PREFIX, ParsedMessage

# A tool telling the person someone mentioned them: Jira, Confluence, GitHub, Teams.
TOLD = re.compile(r"\bmentioned you\b", re.I)
# How much of the line that named them is kept to show why.
QUOTE_LENGTH = 140


def path(home: Path) -> Path:
    return home / "system" / "me.json"


def load(home: Path) -> MailMe | None:
    file = path(home)
    if not file.exists():
        return None
    return MailMe.model_validate(json.loads(file.read_text(encoding="utf-8")))


def save(home: Path, me: MailMe) -> None:
    file = path(home)
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(f"{file.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(me.model_dump_json(indent=2), encoding="utf-8")
    replace_file(temporary, file)


def found(name: str, addresses: list[str]) -> MailMe:
    """What the account says about the person, before they change anything: their full name,
    their first name, and the part of each address before the @, which is how tools tag them."""
    words = name.split()
    names = [name] if words else []
    if len(words) >= 2:
        names.append(words[0])
    ids = [address.partition("@")[0] for address in addresses]
    return MailMe(
        names=list(dict.fromkeys(names)),
        addresses=list(dict.fromkeys(addresses)),
        ids=[item for item in dict.fromkeys(ids) if item],
    )


def name_from(senders: list[str]) -> str:
    """The name the person sends as, most often."""
    counted = Counter(name.strip() for name in senders if name.strip() and "@" not in name)
    return counted.most_common(1)[0][0] if counted else ""


def _said(text: str, me: MailMe) -> str:
    """The text with other people's names blanked, so "Mahesh Kumar" isn't read as "Mahesh"."""
    for other in me.not_you:
        if other.strip():
            blank = re.compile(re.escape(other.strip()), re.I)
            text = blank.sub(lambda m: " " * len(m.group()), text)
    return text


def _surnames(me: MailMe) -> set[str]:
    """What may follow one of the person's names and still be them: "Mahesh Yadav"."""
    return {word.casefold() for name in me.names for word in name.split()[1:]}


def _words(me: MailMe) -> list[str]:
    """Everything that names the person, longest first, so "Mahesh Yadav" wins over "Mahesh".
    The part of an address before the @ counts only as one of their ids, so taking it off the
    list stops it."""
    return sorted({*me.names, *me.addresses, *me.ids} - {""}, key=len, reverse=True)


def _match(text: str, word: str, surnames: set[str]) -> re.Match[str] | None:
    # Not inside another word or address: "Maheshwari" isn't "Mahesh".
    pattern = re.compile(rf"(?<![\w.]){re.escape(word.strip())}(?![\w])", re.I)
    for match in pattern.finditer(text):
        # A different capitalised surname right after a single name is someone else.
        after = re.match(r"\s+([A-Z][a-z]+)\b", text[match.end() :])
        if " " not in word.strip() and after and after.group(1).casefold() not in surnames:
            continue
        return match
    return None


def _hit(text: str, me: MailMe) -> re.Match[str] | None:
    surnames = _surnames(me)
    for word in _words(me):
        if found := _match(text, word, surnames):
            return found
    return None


def finder(me: MailMe) -> Callable[[str, str], list[str]]:
    """Which of the person's names an email's own words use, judged as `named` judges them: not
    the quoted mail below, not anyone named like them, and nothing they sent themselves. Built
    once for many emails, so each is a quick look before the full test."""
    own = {address.lower() for address in me.addresses}
    surnames = _surnames(me)
    words = [(word, word.strip().casefold()) for word in _words(me)]

    def find(clean: str, sender: str) -> list[str]:
        if sender.lower() in own or not clean:
            return []
        folded = clean.casefold()
        if not any(needle in folded for _, needle in words):
            return []
        text = _said(clean, me)
        return [word for word, _ in words if _match(text, word, surnames)]

    return find


def _quote(text: str, match: re.Match[str]) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    line = " ".join(text[start : end if end != -1 else len(text)].split())
    return line if len(line) <= QUOTE_LENGTH else line[: QUOTE_LENGTH - 1].rstrip() + "…"


def is_reply(parsed: ParsedMessage) -> bool:
    return bool(SUBJECT_PREFIX.match(parsed.subject) or parsed.in_reply_to)


def told(parsed: ParsedMessage) -> str | None:
    """A tool passing on that a person mentioned them: its subject says so."""
    return parsed.subject.strip() if TOLD.search(parsed.subject) else None


def named(parsed: ParsedMessage, me: MailMe) -> str | None:
    """The words that named the person, from what this message itself says, or None."""
    return named_in(parsed.clean, parsed.from_addr, me)


def named_in(clean: str, sender: str, me: MailMe) -> str | None:
    """The line of an email's own words that named the person, or None: what `named` reads, from
    the stored text alone."""
    if sender.lower() in {address.lower() for address in me.addresses}:
        return None
    text = _said(clean or "", me)
    match = _hit(text, me)
    return _quote(text, match) if match else None
