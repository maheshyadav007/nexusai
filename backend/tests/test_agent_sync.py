"""Posty sees what the app shows: every object has one address, used to open and to cite it, and
no internal key reaches the screen (docs/AGENT_SYNC_PLAN.md)."""

from typing import Any

from nexusai.modules.agent.citations import Citations
from nexusai.modules.agent.ui_stream import UiTranslator


class Read(Citations):
    """What a turn read, without a database, to test the stream on its own."""

    def __init__(self, read: set[tuple[str, str]]) -> None:
        self.read = read
        self.numbers = {}
        self.pages = {}
        self.messages = {}

    def _was_read(self, kind: str, ref: str) -> bool:
        return (kind, ref) in self.read


def stream(chunks: list[str], read: set[tuple[str, str]]) -> str:
    translator = UiTranslator(started=True, citations=Read(read))
    block: dict[str, Any] = {"kind": "text", "id": "t"}
    parts: list[dict[str, Any]] = []
    for chunk in chunks:
        parts += translator._visible_text(block, chunk)
    parts += translator._end_text(block)
    return "".join(part.get("delta", "") for part in parts)


def test_a_matter_a_task_and_a_reminder_are_cited_like_mail() -> None:
    read = {("matter", "12"), ("task", "88"), ("reminder", "5")}
    assert stream(["RCA [matter:1", "2] is done [task:88]; chase [rem", "inder:5]."], read) == (
        "RCA [1](#cite-1) is done [2](#cite-2); chase [3](#cite-3)."
    )


def test_a_bare_key_becomes_a_citation_when_read_and_goes_when_not() -> None:
    read = {("task", "88"), ("doc", "m:12:2"), ("mail", "7")}
    assert stream(["Ticked task:", "88, see m:12", ":2 and thread:7 and task:99."], read) == (
        "Ticked [1](#cite-1), see [2](#cite-2) and [3](#cite-3) and ."
    )


def test_a_bare_key_at_the_very_end_is_still_rewritten() -> None:
    assert stream(["Done: task:9"], set()) == "Done: "


def test_times_links_and_words_are_left_alone() -> None:
    text = "At 21:45 I'm done with the task, see https://x.example/m:12 and ratio 3:2."
    assert stream([text[:9], text[9:30], text[30:]], set()) == text
