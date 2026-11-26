"""Routines that start on a check: look at a web address every so often, with no model, and tell
the person once when it goes down and once when it's back.

Two failures in a row count as down, so one slow answer doesn't raise an alarm, and a check that
stays down isn't told about again. Nothing is sent to anyone else: telling others needs the
person's yes, which a check running by itself can't get. See docs/SCHEDULES_AND_MONITORS_PLAN.md.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from nexusai.contracts.agent import CheckList, RoutineCheck, SaveCheck
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import channel

log = structlog.get_logger()
MIGRATION = Migration(
    "agent_routine_checks_001",
    """
CREATE TABLE routine_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, url TEXT NOT NULL,
  every_minutes INTEGER NOT NULL, expect_status INTEGER NOT NULL DEFAULT 200,
  enabled INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'unknown',
  failures INTEGER NOT NULL DEFAULT 0, alerted INTEGER NOT NULL DEFAULT 0,
  next_check TEXT, last_checked TEXT, last_result TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
""",
)
NOTICE_KIND = "check"
# Two in a row before it counts as down, so a single slow answer doesn't flap.
FAILURES_TO_ALERT = 2
TIMEOUT_SECONDS = 10.0
LINK = "/agent/schedules"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _row(row: Any) -> RoutineCheck:
    return RoutineCheck(
        id=row["id"],
        title=row["title"],
        url=row["url"],
        every_minutes=row["every_minutes"],
        expect_status=row["expect_status"],
        enabled=bool(row["enabled"]),
        state=row["state"],
        failures=row["failures"],
        next_check=row["next_check"],
        last_checked=row["last_checked"],
        last_result=row["last_result"],
    )


def listing(ctx: Context) -> CheckList:
    rows = ctx.bus.db.fetch_all("SELECT * FROM routine_checks ORDER BY id")
    return CheckList(checks=[_row(row) for row in rows])


def _url(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CommandError(
            "check.url", f"{value!r} isn't a web address. Use one starting with https://.", 422
        )
    return text


def save(ctx: Context, command: SaveCheck) -> CheckList:
    url = _url(command.url)
    now = _iso(_now())
    with ctx.bus.unit_of_work() as work:
        if command.id is None:
            work.tx.execute(
                "INSERT INTO routine_checks (title, url, every_minutes, expect_status, enabled,"
                " next_check, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    command.title.strip(),
                    url,
                    command.every_minutes,
                    command.expect_status,
                    int(command.enabled),
                    now,
                    now,
                    now,
                ),
            )
        else:
            changed = work.tx.execute(
                "UPDATE routine_checks SET title = ?, url = ?, every_minutes = ?, expect_status = ?,"
                " enabled = ?, next_check = COALESCE(next_check, ?), updated = ? WHERE id = ?",
                (
                    command.title.strip(),
                    url,
                    command.every_minutes,
                    command.expect_status,
                    int(command.enabled),
                    now,
                    now,
                    command.id,
                ),
            ).rowcount
            if not changed:
                raise CommandError("check.not_found", "That check is gone.", 404)
        work.emit("checks.changed", {}, source="agent", trace_id=ctx.trace_id)
    return listing(ctx)


def remove(ctx: Context, identifier: int) -> CheckList:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute("DELETE FROM routine_checks WHERE id = ?", (identifier,))
        work.emit("checks.changed", {}, source="agent", trace_id=ctx.trace_id)
    return listing(ctx)


def next_due(ctx: Context) -> str | None:
    rows = ctx.bus.db.fetch_all(
        "SELECT MIN(next_check) AS due FROM routine_checks WHERE enabled = 1"
    )
    return rows[0]["due"] if rows else None


def look(url: str, expect: int) -> tuple[bool, str]:
    """Whether the address answers as expected, and what it said, in a few words."""
    try:
        response = httpx.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.TimeoutException:
        return False, f"No answer in {int(TIMEOUT_SECONDS)} seconds"
    except httpx.HTTPError as error:
        return False, f"Couldn't reach it: {type(error).__name__}"
    if response.status_code != expect:
        return False, f"Answered {response.status_code}, expected {expect}"
    return True, f"Answered {response.status_code}"


def run(ctx: Context, identifier: int, now: datetime | None = None) -> RoutineCheck:
    """Checks it once now, moves its next check on, and tells the person if its state changed."""
    rows = ctx.bus.db.fetch_all("SELECT * FROM routine_checks WHERE id = ?", (identifier,))
    if not rows:
        raise CommandError("check.not_found", "That check is gone.", 404)
    row = rows[0]
    at = now or _now()
    ok, said = look(row["url"], row["expect_status"])
    failures = 0 if ok else row["failures"] + 1
    down = failures >= FAILURES_TO_ALERT
    state = "ok" if ok else "failing" if down else row["state"]
    with ctx.bus.unit_of_work() as work:
        alerted = row["alerted"]
        if down and not alerted:
            channel.notify(ctx, work, f"Down: {row['title']}", said, LINK, NOTICE_KIND, True)
            alerted = 1
        elif ok and alerted:
            channel.notify(ctx, work, f"Back up: {row['title']}", said, LINK, NOTICE_KIND, False)
            alerted = 0
        work.tx.execute(
            "UPDATE routine_checks SET state = ?, failures = ?, alerted = ?, last_checked = ?,"
            " last_result = ?, next_check = ?, updated = ? WHERE id = ?",
            (
                state,
                failures,
                alerted,
                _iso(at),
                said,
                _iso(at + timedelta(minutes=row["every_minutes"])),
                _iso(at),
                identifier,
            ),
        )
        work.emit("checks.changed", {}, source="agent", trace_id=ctx.trace_id)
    return _row(ctx.bus.db.fetch_all("SELECT * FROM routine_checks WHERE id = ?", (identifier,))[0])


def run_due(ctx: Context, now: datetime) -> int:
    """Every check whose time has come, including those missed while the computer slept: each is
    checked once, not once for every time it missed."""
    at = now.astimezone(UTC)
    rows = ctx.bus.db.fetch_all(
        "SELECT id FROM routine_checks WHERE enabled = 1 AND next_check IS NOT NULL"
        " AND next_check <= ? ORDER BY next_check",
        (_iso(at),),
    )
    for row in rows:
        try:
            run(ctx, row["id"], at)
        except Exception:
            # One broken check mustn't stop the others.
            log.exception("check_failed", check=row["id"])
    return len(rows)
