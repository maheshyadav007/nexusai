"""The speed targets in docs/ARCHITECTURE.md, on a generated mailbox with encryption on.

Run with `make speed`. Building the mailbox takes a while, so the everyday test run skips it.
"""

import random
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from nexusai.api.app import BUS_MIGRATIONS, MODULES, _open_database
from nexusai.contracts.mail import SearchMail
from nexusai.kernel import backups
from nexusai.kernel.config import Config
from nexusai.kernel.database import Database
from nexusai.modules.mail import store
from nexusai.modules.mail.parse import ParsedMessage
from nexusai.modules.semantic.catalog import DIMENSIONS
from nexusai.modules.semantic.index import VectorIndex

pytestmark = pytest.mark.speed

MESSAGES = 100_000
BATCH = 2_000
REPEATS = 30
ACCOUNT = "speed"
OPEN_TARGET_MS = 200
SEARCH_TARGET_MS = 300
NEW_MAIL_TARGET_MS = 1000
LAUNCH_TARGET_SECONDS = 3
WORDS = [
    "budget",
    "review",
    "contract",
    "vendor",
    "renewal",
    "schedule",
    "meeting",
    "report",
    "forecast",
    "design",
    "customer",
    "release",
    "quality",
    "supplier",
    "invoice",
    "roadmap",
    "staffing",
    "training",
    "approval",
    "travel",
    "security",
    "audit",
    "deadline",
    "launch",
    "hardware",
    "firmware",
    "display",
    "memory",
    "battery",
    "camera",
    "sensor",
    "payment",
    "margin",
    "quarter",
    "project",
    "milestone",
    "risk",
    "summary",
    "update",
    "request",
    "response",
]
RARE = "zephyrine"
RARE_EVERY = 5_000
KEY = "ef" * 32


def parsed(number: int, rng: random.Random, when: datetime, parent: str | None) -> ParsedMessage:
    subject_words = rng.choices(WORDS, k=5)
    body = " ".join(rng.choices(WORDS, k=rng.randint(80, 400)))
    if number % RARE_EVERY == 0:
        body += f" {RARE}"
    message_id = f"<m{number}@speed.example>"
    return ParsedMessage(
        message_id=message_id,
        in_reply_to=parent,
        references=[parent] if parent else [],
        thread_index_root=None,
        subject=" ".join(subject_words),
        from_name=f"Person {number % 500}",
        from_addr=f"person{number % 500}@speed.example",
        to=["me@speed.example"],
        cc=[],
        date=when.isoformat(),
        text=body,
        html=None,
        own=body,
        clean=body,
        snippet=body[:160],
        encrypted=None,
        signed=False,
        headers={},
    )


@dataclass
class Mailbox:
    db: Database
    config: Config
    threads: list[int]
    built_seconds: float


@pytest.fixture(scope="module")
def mailbox(tmp_path_factory: pytest.TempPathFactory) -> Any:
    from nexusai.kernel.config import load_config

    home: Path = tmp_path_factory.mktemp("speed")
    config = replace(load_config(home), home_dir=home)
    db = Database(home / "system" / "nexusai.db", KEY)
    db.migrate(BUS_MIGRATIONS)
    for module in MODULES:
        db.migrate(module.migrations)
    rng = random.Random(7)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    began = time.perf_counter()
    latest: list[str] = []
    threads: set[int] = set()
    number = 0
    while number < MESSAGES:
        with db.transaction() as tx:
            for _ in range(min(BATCH, MESSAGES - number)):
                # About a third of mail replies to something recent, as real conversations do.
                parent = rng.choice(latest) if latest and rng.random() < 0.35 else None
                message = parsed(number, rng, start + timedelta(minutes=number), parent)
                stored = store.store_message(
                    tx,
                    account=ACCOUNT,
                    folder="INBOX",
                    role="inbox",
                    uid=number + 1,
                    raw=message.text.encode(),
                    read=number % 3 == 0,
                    flagged=False,
                    parsed=message,
                    match=None,
                    config=config.mail,
                )
                assert stored
                threads.add(stored.thread)
                latest = [*latest[-200:], message.message_id]
                number += 1
    built = time.perf_counter() - began
    yield Mailbox(db, config, sorted(threads), built)
    db.close()


def timed(action: Callable[[int], object], repeats: int = REPEATS) -> tuple[float, float]:
    """Median and slowest in milliseconds, leaving out the first, which fills the page cache."""
    action(0)
    samples = []
    for index in range(1, repeats + 1):
        began = time.perf_counter()
        action(index)
        samples.append((time.perf_counter() - began) * 1000)
    return statistics.median(samples), max(samples)


def report(name: str, median: float, slowest: float, target: float) -> None:
    print(f"\n{name}: median {median:.1f} ms, slowest {slowest:.1f} ms, target {target} ms")


def test_the_mailbox_is_the_promised_size(mailbox: Mailbox) -> None:
    rows = mailbox.db.fetch_all("SELECT COUNT(*) FROM messages")
    assert rows[0][0] == MESSAGES
    print(
        f"\nBuilt {MESSAGES} messages in {mailbox.built_seconds:.0f} s, {len(mailbox.threads)} conversations"
    )


def test_opening_the_inbox(mailbox: Mailbox) -> None:
    median, slowest = timed(
        lambda _: store.list_threads(mailbox.db, ACCOUNT, "inbox", None, None, 50)
    )
    report("Inbox", median, slowest, OPEN_TARGET_MS)
    assert slowest < OPEN_TARGET_MS


def test_paging_deep_into_the_inbox(mailbox: Mailbox) -> None:
    first = store.list_threads(mailbox.db, ACCOUNT, "inbox", None, None, 50)
    cursor = first.next_before
    for _ in range(100):
        page = store.list_threads(mailbox.db, ACCOUNT, "inbox", None, cursor, 50)
        cursor = page.next_before
    median, slowest = timed(
        lambda _: store.list_threads(mailbox.db, ACCOUNT, "inbox", None, cursor, 50)
    )
    report("Inbox, 100 pages in", median, slowest, OPEN_TARGET_MS)
    assert slowest < OPEN_TARGET_MS


def test_opening_a_thread(mailbox: Mailbox) -> None:
    rng = random.Random(3)
    assert store.thread_view(mailbox.db, mailbox.threads[0])
    median, slowest = timed(lambda _: store.thread_view(mailbox.db, rng.choice(mailbox.threads)))
    report("Thread", median, slowest, OPEN_TARGET_MS)
    assert slowest < OPEN_TARGET_MS


@pytest.mark.parametrize(
    ("label", "words"),
    [("common word", "budget"), ("two common words", "budget review"), ("rare word", RARE)],
)
def test_keyword_search(mailbox: Mailbox, label: str, words: str) -> None:
    query = SearchMail(query=words)
    median, slowest = timed(lambda _: store.search(mailbox.db, ACCOUNT, query))
    report(f"Search, {label}", median, slowest, SEARCH_TARGET_MS)
    assert store.search(mailbox.db, ACCOUNT, query).hits
    assert slowest < SEARCH_TARGET_MS


def test_search_with_only_a_filter_and_with_a_filter_on_a_common_word(mailbox: Mailbox) -> None:
    for label, query in [
        ("by sender", SearchMail(sender="person42@")),
        ("common word and sender", SearchMail(query="budget", sender="person42@")),
        ("date range only", SearchMail(date_from="2024-02-01", date_to="2024-02-20")),
        ("folder only", SearchMail(folder="inbox")),
    ]:
        median, slowest = timed(lambda _, q=query: store.search(mailbox.db, ACCOUNT, q))
        report(f"Search, {label}", median, slowest, SEARCH_TARGET_MS)
        assert store.search(mailbox.db, ACCOUNT, query).hits
        assert slowest < SEARCH_TARGET_MS


def test_a_rare_word_finds_old_mail_and_a_common_one_shows_recent_mail(mailbox: Mailbox) -> None:
    rare = store.search(mailbox.db, ACCOUNT, SearchMail(query=RARE)).hits
    # Every match is reachable when there are few, including the very oldest.
    assert len(rare) >= (MESSAGES // RARE_EVERY) * 0.9
    assert any(hit.message_id == 1 for hit in rare)
    common = store.search(mailbox.db, ACCOUNT, SearchMail(query="budget")).hits
    assert all(hit.message_id > MESSAGES - 20_000 for hit in common)


def test_opening_a_large_home_does_not_wait_for_a_backup(mailbox: Mailbox) -> None:
    home = mailbox.config.home
    began = time.perf_counter()
    db, _ = _open_database(mailbox.config, home, KEY)
    seconds = time.perf_counter() - began
    db.close()
    print(
        f"\nOpening the database: {seconds * 1000:.0f} ms, target {LAUNCH_TARGET_SECONDS} s in all"
    )
    assert seconds < LAUNCH_TARGET_SECONDS / 3
    assert not backups.listing(home)


def test_new_mail_reaches_the_store(mailbox: Mailbox) -> None:
    rng = random.Random(11)
    when = datetime(2030, 1, 1, tzinfo=UTC)

    def arrive(index: int) -> None:
        number = MESSAGES + 1000 + index
        message = parsed(number, rng, when + timedelta(minutes=index), None)
        with mailbox.db.transaction() as tx:
            store.store_message(
                tx,
                account=ACCOUNT,
                folder="INBOX",
                role="inbox",
                uid=number,
                raw=message.text.encode(),
                read=False,
                flagged=False,
                parsed=message,
                match=None,
                config=mailbox.config.mail,
            )

    median, slowest = timed(arrive)
    report("New mail stored", median, slowest, NEW_MAIL_TARGET_MS)
    assert slowest < NEW_MAIL_TARGET_MS


def test_search_by_meaning_stays_quick() -> None:
    # A mailbox this size holds more chunks than messages, since long mail is split.
    chunks = MESSAGES * 2
    rng = np.random.default_rng(13)
    index = VectorIndex(cast(Database, None), "mail", "speed")
    index.vectors = rng.integers(-127, 127, (chunks, DIMENSIONS), dtype=np.int8)
    index.rows = [(str(number // 2), number % 2) for number in range(chunks)]
    query = rng.normal(size=DIMENSIONS).astype(np.float32)
    query /= np.linalg.norm(query)

    median, slowest = timed(lambda _: index.search(query, 200))
    report("Search by meaning", median, slowest, SEARCH_TARGET_MS)
    assert median < SEARCH_TARGET_MS
