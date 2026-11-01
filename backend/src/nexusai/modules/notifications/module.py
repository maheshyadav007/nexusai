from datetime import UTC, datetime

from nexusai.contracts.events import AppEvent
from nexusai.contracts.notifications import (
    ListNotifications,
    MarkNotificationsRead,
    Notification,
    NotificationList,
    NotificationRequested,
    NotificationsChanged,
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
        )
    ],
)
PAGE = 200


def _unread(ctx: Context) -> int:
    rows = ctx.bus.db.fetch_all("SELECT COUNT(*) AS n FROM notifications WHERE read = 0")
    return int(rows[0]["n"])


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
        unread = work.tx.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()[0]
        work.emit(
            "notifications.changed",
            NotificationsChanged(unread=unread).model_dump(),
            source=notifications_module.name,
            trace_id=event.trace_id,
            cause=event,
        )


@notifications_module.query("notifications.list")
def list_notifications(query: ListNotifications, ctx: Context) -> NotificationList:
    where, params = ("WHERE kind = ?", (query.kind, PAGE)) if query.kind else ("", (PAGE,))
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM notifications {where} ORDER BY id DESC LIMIT ?",  # noqa: S608
        params,
    )
    kinds = ctx.bus.db.fetch_all("SELECT DISTINCT kind FROM notifications ORDER BY kind")
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
        unread = work.tx.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()[0]
        work.emit(
            "notifications.changed",
            NotificationsChanged(unread=unread).model_dump(),
            source=notifications_module.name,
            trace_id=ctx.trace_id,
        )
    return NotificationsChanged(unread=unread)
