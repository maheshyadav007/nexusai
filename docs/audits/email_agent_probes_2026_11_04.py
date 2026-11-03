"""Observe current reliability flaws using synthetic in-memory state; no model or live Home."""

import sqlite3
import threading
from datetime import datetime
from types import SimpleNamespace as NS
from contextlib import contextmanager
from unittest.mock import patch
from nexusai.modules.agent import triggers, scheduler, mail_agent


class DB:
    def __init__(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row

    def fetch_all(self, q, args=()):
        return self.c.execute(q, args).fetchall()

    @contextmanager
    def transaction(self):
        with self.c:
            yield self.c


D = DB()
D.c.executescript(
    """CREATE TABLE agent_triggers(id,kind,enabled,prompt,context_mode,keep_messages,token_limit); INSERT INTO agent_triggers VALUES('test','custom',1,'Review every conversation',NULL,NULL,0); CREATE TABLE trigger_runs(id,trigger,thread,status,session,turn); CREATE TABLE agent_defaults(key,value); CREATE TABLE work_board(id,kind,title,thread,due,done);"""
)
for i in range(1, 6):
    D.c.execute("INSERT INTO trigger_runs VALUES(?, 'test', ?, 'pending', NULL, NULL)", (i, i))


@contextmanager
def work():
    with D.transaction() as tx:
        yield NS(tx=tx)


ctx = NS(bus=NS(db=D, unit_of_work=work), config=NS(agent=NS(learn_emails=0)))
t = triggers.Triggers.__new__(triggers.Triggers)
t.ctx = ctx
t.config = ctx.config.agent
t.lock = threading.RLock()
t.wake = threading.Event()
t._model_ready = lambda: True
t._trigger_session = lambda row: "s"
seen = []
t._threads_text = lambda session, threads: seen.extend(threads) or "email data"
t.runtime = NS(active_turn=lambda s: None, dispatch=lambda req: 7)
with patch.object(triggers.gateway, "set_run_limit"):
    t._start_custom()
print(
    "BURST:",
    len(seen),
    "threads supplied;",
    D.fetch_all("SELECT COUNT(*) n FROM trigger_runs WHERE turn=7")[0]["n"],
    "events assigned to that run",
)
D.c.execute(
    "INSERT INTO work_board VALUES(1,'deadline','Unfinished obligation',NULL,'2020-01-01',0)"
)
s = scheduler.Scheduler.__new__(scheduler.Scheduler)
s.ctx = ctx

with patch.object(scheduler.channel, "notify"):
    s._overdue(datetime(2026, 11, 4))
print("OVERDUE:", dict(D.fetch_all("SELECT title,done FROM work_board")[0]))
with (
    patch.object(mail_agent, "enabled", return_value=True),
    patch.object(mail_agent, "settle") as settled,
):
    t.consider_learning(True)
    t._start_schedule(99, {"kind": triggers.BRIEF_KIND})
    print(
        "ZERO LEARNING:",
        repr(mail_agent.learning_state(ctx)),
        "brief settlement:",
        settled.call_args.args[1:],
    )
# Force the completion callback at the earliest legal worker time, before dispatch returns.
observed = []


def finish_first(req):
    observed.append(
        D.fetch_all("SELECT COUNT(*) n FROM trigger_runs WHERE turn=8 AND status='running'")[0]["n"]
    )
    return 8


t.runtime.dispatch = finish_first
with patch.object(triggers.gateway, "set_run_limit"):
    t._dispatch(triggers.TurnRequest("s", "test"), [1], 0)
print(
    "DISPATCH ORDER:",
    observed[0],
    "associated running events visible during early completion;",
    D.fetch_all("SELECT status FROM trigger_runs WHERE id=1")[0]["status"],
    "after dispatch",
)
