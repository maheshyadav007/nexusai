"""A brief counts as out of date only once a newer one was due."""

from datetime import datetime, timedelta

from nexusai.kernel.module import Context
from nexusai.modules.agent import module as agent
from test_mail_organization import ctx  # noqa: F401


def morning_brief_at(ctx: Context, when: datetime) -> None:  # noqa: F811
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM schedules WHERE kind = 'mail-brief'")
        tx.execute(
            "INSERT INTO schedules (title, prompt, kind, every, time) VALUES"
            " ('Morning brief', '', 'mail-brief', 'day', ?)",
            (when.strftime("%H:%M"),),
        )


def test_last_evenings_brief_is_not_stale_after_midnight(ctx: Context) -> None:  # noqa: F811
    now = datetime.now().astimezone()
    # No morning brief scheduled: nothing newer is coming, so nothing is overdue.
    with ctx.bus.db.transaction() as tx:
        tx.execute("DELETE FROM schedules WHERE kind = 'mail-brief'")
    assert not agent._brief_overdue(ctx, now - timedelta(days=3))
    # The morning run is an hour away: the brief from before it is still the newest.
    morning_brief_at(ctx, now + timedelta(hours=1))
    assert not agent._brief_overdue(ctx, now - timedelta(hours=5))


def test_a_brief_is_stale_once_the_morning_run_should_have_replaced_it(ctx: Context) -> None:  # noqa: F811
    now = datetime.now().astimezone()
    morning_brief_at(ctx, now - timedelta(hours=2))
    assert agent._brief_overdue(ctx, now - timedelta(hours=3))
    # Written by that run, or after it, it's current.
    assert not agent._brief_overdue(ctx, now - timedelta(hours=1))
