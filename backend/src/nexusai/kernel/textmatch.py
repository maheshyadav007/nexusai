"""Whether two short texts say the same thing, so agents don't ask the person twice."""

import re

# Words that carry no meaning of their own, so "Reply to Priya about the budget" and
# "Respond to Priya re budget" compare on what they're about.
_FILLER = frozenset(
    """a an the to of for on in at by with about re and or is are be please your my their
    this that it its from""".split()  # noqa: SIM905
)
_SAME_ACTION = {
    "respond": "reply",
    "answer": "reply",
    "send": "share",
    "confirm": "confirm",
    "check": "review",
    "look": "review",
}


def words(text: str) -> frozenset[str]:
    found = (word for word in re.findall(r"\w+", text.casefold()) if word not in _FILLER)
    return frozenset(_SAME_ACTION.get(word, word) for word in found)


def same(first: str, second: str, threshold: float = 0.75) -> bool:
    """Same words once filler, case and punctuation are set aside, or nearly so."""
    a, b = words(first), words(second)
    if not a or not b:
        return False
    if a == b:
        return True
    overlap = len(a & b)
    # One is the other with a word or two more: "Send the Q3 numbers" / "Send Q3 numbers to Meera".
    if overlap == min(len(a), len(b)) and min(len(a), len(b)) >= 3:
        return True
    return overlap / len(a | b) >= threshold
