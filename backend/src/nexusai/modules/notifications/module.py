from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.events import AppEvent
from nexusai.contracts.notifications import (
    ClearNotifications,
    ListNotifications,
    MarkNotificationsRead,
    Notification,
    NotificationList,
    NotificationRequested,
    NotificationsChanged,
    NotificationsCleared,
    RestoreNotifications,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context, Module

notifications_module = Module(
    name="notifications",
    migrations=[
        Migration(
            "notifications_001",
            "CREATE TABLE notifications ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, kind TEXT NOT NULL,"
            " title TEXT NOT NULL, detail TEXT NOT NULL, link TEXT,"
            " read INTEGER NOT NULL DEFAULT 0)",
        ),
        # Cleared ones are kept until Undo has passed, and then never listed again.
        Migration("notifications_002", "ALTER TABLE notifications ADD COLUMN cleared TEXT"),
    ],
)
PAGE = 200
UNREAD = "SELECT COUNT(*) FROM notifications WHERE read = 0 AND cleared IS NULL"


def _unread(ctx: Context) -> int:
    return int(ctx.bus.db.fetch_all(UNREAD.replace("COUNT(*)", "COUNT(*) AS n"))[0]["n"])


def _changed(work: Any, ctx: Context) -> int:
    unread = int(work.tx.execute(UNREAD).fetchone()[0])
    work.emit(
        "notifications.changed",
        NotificationsChanged(unread=unread).model_dump(),
        source=notifications_module.name,
        trace_id=ctx.trace_id,
    )
    return unread


@notifications_module.on("notification.requested", "notifications.store")
def store(event: AppEvent, ctx: Context) -> None:
    request = NotificationRequested.model_validate(event.payload)
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO notifications (time, kind, title, detail, link) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                request.kind,
                request.title,
                request.detail,
                request.link,
            ),
        )
        unread = work.tx.execute(UNREAD).fetchone()[0]
        work.emit(
            "notifications.changed",
            NotificationsChanged(unread=unread).model_dump(),
            source=notifications_module.name,
            trace_id=event.trace_id,
            cause=event,
        )


@notifications_module.query("notifications.list")
def list_notifications(query: ListNotifications, ctx: Context) -> NotificationList:
    where, params = ("AND kind = ?", (query.kind, PAGE)) if query.kind else ("", (PAGE,))
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM notifications WHERE cleared IS NULL {where}"  # noqa: S608
        " ORDER BY id DESC LIMIT ?",
        params,
    )
    kinds = ctx.bus.db.fetch_all(
        "SELECT DISTINCT kind FROM notifications WHERE cleared IS NULL ORDER BY kind"
    )
    return NotificationList(
        items=[Notification(**{**dict(row), "read": bool(row["read"])}) for row in rows],
        unread=_unread(ctx),
        kinds=[row["kind"] for row in kinds],
    )


@notifications_module.command("notifications.markRead")
def mark_read(command: MarkNotificationsRead, ctx: Context) -> NotificationsChanged:
    with ctx.bus.unit_of_work() as work:
        if command.id is None:
            work.tx.execute("UPDATE notifications SET read = 1 WHERE read = 0")
        else:
            work.tx.execute("UPDATE notifications SET read = 1 WHERE id = ?", (command.id,))
        unread = _changed(work, ctx)
    return NotificationsChanged(unread=unread)


@notifications_module.command("notifications.clear")
def clear(command: ClearNotifications, ctx: Context) -> NotificationsCleared:
    where, params = ("AND kind = ?", (command.kind,)) if command.kind else ("", ())
    with ctx.bus.unit_of_work() as work:
        ids = [
            row[0]
            for row in work.tx.execute(
                f"SELECT id FROM notifications WHERE cleared IS NULL {where}",  # noqa: S608
                params,
            ).fetchall()
        ]
        work.tx.executemany(
            "UPDATE notifications SET cleared = ? WHERE id = ?",
            [(datetime.now(UTC).isoformat(), identifier) for identifier in ids],
        )
        unread = _changed(work, ctx)
    return NotificationsCleared(ids=ids, unread=unread)


@notifications_module.command("notifications.restore")
def restore(command: RestoreNotifications, ctx: Context) -> NotificationsChanged:
    with ctx.bus.unit_of_work() as work:
        work.tx.executemany(
            "UPDATE notifications SET cleared = NULL WHERE id = ?",
            [(identifier,) for identifier in command.ids],
        )
        unread = _changed(work, ctx)
    return NotificationsChanged(unread=unread)
