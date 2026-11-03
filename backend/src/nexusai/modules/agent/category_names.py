"""When two category names mean the same area of work, so mail doesn't end up split between them."""

import re

WORD = re.compile(r"[^\W_]+")
# They say what kind of mail it is, not what it's about, so sharing one doesn't make two the same.
GENERIC_WORDS = frozenset(
    {
        "all",
        "alert",
        "and",
        "announcement",
        "communication",
        "email",
        "feedback",
        "for",
        "general",
        "info",
        "information",
        "internal",
        "mail",
        "message",
        "misc",
        "new",
        "news",
        "notice",
        "notification",
        "other",
        "personal",
        "project",
        "related",
        "request",
        "team",
        "the",
        "update",
        "work",
    }
)


def _words(name: str) -> set[str]:
    found = {word.casefold().removesuffix("s") for word in WORD.findall(name)}
    return found - GENERIC_WORDS


def same_area(one: str, other: str) -> bool:
    """HR, HR feedback and HR communication are one area. Updates and Product updates aren't."""
    if one.strip().casefold() == other.strip().casefold():
        return True
    return bool(_words(one) & _words(other))


def area_of(name: str, among: list[str]) -> str | None:
    """The shortest name already in this area, since it's usually the broadest."""
    return next((known for known in sorted(among, key=len) if same_area(name, known)), None)
