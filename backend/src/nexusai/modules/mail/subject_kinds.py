"""The kinds of mail one sender sends, found from its subjects alone: "Your OTP for login is 4821"
and "Your OTP for login is 1193" are one kind, "Rs 2,450 debited from your account XX8812" another.

Each subject becomes a bag of the words that are written the same every time: numbers, ids and
amounts (any word with a digit), dates in words, the person's own name and filler words are left
out, and a
[tag] is kept apart. Subjects are taken most common first, each joining the first kind whose
words it mostly shares, so the same mail always gives the same kinds. A kind is named by its
core, the words nearly all its emails carry, and kept only when that core, as a rule, catches its
own mail and little else. Whatever fits no kind is out of the ordinary, and the AI reads it.

Only the parser, so the Sort lab can use it without the database or the keychain.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from nexusai.modules.mail.parse import SUBJECT_TAG, subject_words, tags_of

# Kinds must cover this share of a sender's mail, or one word they nearly all share is the kind.
MOSTLY = 0.75
# A sender's kinds must explain this share of its mail, or it has no kinds: all of it is one.
SETTLED = 0.8
# A subject joins a kind when it shares this much of its words with the kind's first subject.
ALIKE = 0.6
# A word is part of a kind's core when this share of its emails carry it.
CORE = 0.9
# A kind's rule must catch mostly its own mail: of what it catches, at least this share.
PRECISE = 0.95
# Two emails are enough to show a kind repeats.
AT_LEAST = 2
# A core this short says too little, unless a tag says the rest.
FEWEST_WORDS = 2
# Words that make unrelated subjects look alike and say nothing about what an email is.
FILLER = frozenset(
    """a about after again all am an and any are as at be been before being but by can could
    did do does done for from had has have he her here hers him his how i if in into is it its
    just me more most my new no not now of off on once only or our out over own same she should
    so some such than that the their them then there these they this those to too under until
    up very was we were what when where which while who whom why will with would you your yours
    re fw fwd hi hello dear""".split()  # noqa: SIM905
)


# Words that change from one email to the next like numbers do: dates said in words.
DATES = frozenset(
    """jan january feb february mar march apr april may jun june jul july aug august sep sept
    september oct october nov november dec december mon monday tue tues tuesday wed wednesday
    thu thur thurs thursday fri friday sat saturday sun sunday today tomorrow yesterday""".split()  # noqa: SIM905
)


@dataclass(frozen=True)
class Kind:
    """One kind of mail from a sender: its tag, if it has one, and the words nearly all of it
    carries. Its rule is the sender, the tag and every one of the words."""

    tag: str
    words: tuple[str, ...]
    count: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class Seen:
    """One subject: its first tag, its words that don't change, and as written."""

    tag: str
    words: frozenset[str]
    subject: str


@dataclass(frozen=True)
class Kinds:
    kinds: tuple[Kind, ...]
    # Emails that fit no kind: out of the ordinary, so the AI reads them.
    odd: int
    total: int
    odd_examples: tuple[str, ...] = ()


def bag(subject: str, own: frozenset[str]) -> frozenset[str]:
    """The words of a subject that are written the same every time."""
    return frozenset(
        word
        for word in subject_words(subject)
        if len(word) > 1
        and word not in FILLER
        and word not in DATES
        and word not in own
        and not any(ch.isdigit() for ch in word)
    )


def first_tag(subject: str) -> str:
    tags = tags_of(subject)
    return tags[0].casefold() if tags else ""


def matches(kind: Kind, subject: str) -> bool:
    """Whether the kind's rule catches this subject: its tag, and every one of its words."""
    if kind.tag and kind.tag not in {tag.casefold() for tag in tags_of(subject)}:
        return False
    return set(kind.words) <= set(subject_words(subject))


def _alike(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def own_words(name: str, address: str) -> frozenset[str]:
    """The person's own name, as subjects that greet them spell it."""
    local = address.partition("@")[0]
    return frozenset(word for word in subject_words(f"{name} {local}") if len(word) > 1)


def _ticket(subject: str) -> bool:
    """Whether the subject's first tag carries a number, like [RND-1112]: a ticket, not a tool."""
    found = SUBJECT_TAG.search(subject or "")
    return bool(found and any(ch.isdigit() for ch in found.group(1)))


def _kind(
    seen: Sequence[Seen], tag: str, core: tuple[str, ...], members: Iterable[int]
) -> Kind | None:
    """The kind, if its rule catches mostly its own mail among all the sender's."""
    probe = Kind(tag, core, 0, ())
    caught = [i for i, item in enumerate(seen) if matches(probe, item.subject)]
    if not caught or len(set(caught) & set(members)) / len(caught) < PRECISE:
        return None
    return Kind(tag, core, len(caught), tuple(seen[i].subject for i in caught[:3]))


def _core(seen: Sequence[Seen], members: Sequence[int]) -> tuple[str, ...]:
    carried = Counter(word for i in members for word in seen[i].words)
    return tuple(sorted(w for w, n in carried.items() if n / len(members) >= CORE))


def _clustered(seen: Sequence[Seen], bucket: Sequence[int], tag: str) -> list[Kind]:
    """Subjects most common first, each joining the first kind whose words it mostly shares."""
    counts = Counter(seen[i].words for i in bucket)
    order = sorted(counts, key=lambda words: (-counts[words], sorted(words)))
    groups: list[tuple[frozenset[str], list[int]]] = []
    for words in order:
        if not words and not tag:
            continue
        members = [i for i in bucket if seen[i].words == words]
        home = next((g for g in groups if _alike(g[0], words) >= ALIKE), None)
        if home is None:
            groups.append((words, members))
        else:
            home[1].extend(members)
    found = []
    for _, members in groups:
        if len(members) < AT_LEAST:
            continue
        core = _core(seen, members)
        if len(core) < FEWEST_WORDS and not (tag and core):
            continue
        if kind := _kind(seen, tag, core, members):
            found.append(kind)
    return found


def find(subjects: Sequence[str], own: Iterable[str] = ()) -> Kinds:
    """The kinds among one sender's subjects, biggest first, and how many fit none."""
    mine = frozenset(own)
    seen = [Seen(first_tag(subject), bag(subject, mine), subject) for subject in subjects]
    buckets: dict[str, list[int]] = {}
    for i, item in enumerate(seen):
        buckets.setdefault(item.tag, []).append(i)
    found: dict[tuple[str, tuple[str, ...]], Kind] = {}
    for tag, bucket in sorted(buckets.items()):
        if len(bucket) < AT_LEAST:
            continue
        # A ticket's tag, like [RND-1112], names one item; the titles after it are its own. The
        # tool is the kind: every ticket of it, whatever it's called.
        if tag and sum(_ticket(seen[i].subject) for i in bucket) / len(bucket) >= MOSTLY:
            kinds = [k for k in [_kind(seen, tag, (), bucket)] if k]
        else:
            kinds = _clustered(seen, bucket, tag)
            covered = sum(any(matches(k, seen[i].subject) for k in kinds) for i in bucket)
            # Mostly out of the kinds, but nearly all of it shares a word, like "edited" in
            # "Rahul Menon edited 'Roadmap'": the names change, the one word is the kind.
            if covered / len(bucket) < MOSTLY and (core := _core(seen, bucket)):
                kinds = [k for k in [_kind(seen, tag, core, bucket)] if k] or kinds
        for kind in kinds:
            found.setdefault((kind.tag, kind.words), kind)
    kinds_found = tuple(sorted(found.values(), key=lambda k: (-k.count, k.tag, k.words)))
    left = [s for s in subjects if not any(matches(kind, s) for kind in kinds_found)]
    fitted = len(subjects) - len(left)
    # Out of the ordinary only means something where there's an ordinary: a sender whose kinds
    # explain little of its mail, like a store writing a new offer each day, is one kind itself.
    if not subjects or fitted / len(subjects) < SETTLED:
        return Kinds((), 0, len(subjects))
    return Kinds(kinds_found, len(left), len(subjects), tuple(left[:3]))
