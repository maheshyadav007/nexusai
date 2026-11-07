"""The map of the team and the tree of each run, read from what is already recorded.

Nothing here is stored twice: runs, model calls, tool calls, skill loads and tasks are the record,
and these are views of it.
"""

from typing import Any

from nexusai.contracts.agent import AgentMap, MapEdge, RunSpan
from nexusai.kernel.database import Database
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import cards, monitor, team

MOST_SPANS = 400


def agent_map(ctx: Context, running: Any) -> AgentMap:
    db = ctx.bus.db
    edges = []
    for row in db.fetch_all(
        "SELECT * FROM team_tasks WHERE state IN ('queued','working','input_required','blocked','reported')"
        " ORDER BY id"
    ):
        messages = db.fetch_all(
            "SELECT COUNT(*) AS n FROM agent_channel WHERE task = ?", (row["id"],)
        )[0]["n"]
        waiting = {
            "queued": "target",
            "working": "source",
            "blocked": "source",
            "input_required": "target",
            "reported": "target",
        }[row["state"]]
        trouble = None
        if row["state"] == "blocked":
            trouble = team.FAILURES.get(row["failure"] or "", row["failure"] or "Blocked")
        elif messages >= max(2, ctx.config.team.ping_pong_messages - 2):
            trouble = "Many messages back and forth"
        edges.append(
            MapEdge(
                task_id=row["id"],
                source=row["assigner"],
                target=row["owner"],
                state=row["state"],
                objective=row["objective"],
                messages=int(messages),
                # Who is waiting on whom right now: the giver waits while the owner works, and
                # the other way round while a question or a report waits for the giver.
                waiting=row["assigner"] if waiting == "source" else row["owner"],
                trouble=trouble,
            )
        )
    return AgentMap(
        cards=team.listing(ctx, running),
        edges=edges,
        cycles=_cycles(team.waiting_edges(db)),
        alerts=monitor.alerts(db, 20),
    )


def _cycles(edges: list[tuple[str, str, int]]) -> list[list[str]]:
    """Agents waiting on each other. Assigning refuses these, so any found here is a fault."""
    graph: dict[str, set[str]] = {}
    for source, target, _ in edges:
        graph.setdefault(source, set()).add(target)
    found: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    def walk(node: str, path: list[str]) -> None:
        for nxt in graph.get(node, ()):
            if nxt in path:
                loop = path[path.index(nxt) :]
                if frozenset(loop) not in seen:
                    seen.add(frozenset(loop))
                    found.append(loop)
            elif len(path) < 10:
                walk(nxt, [*path, nxt])

    for start in list(graph):
        walk(start, [start])
    return found


def _root(db: Database, turn: int) -> int:
    current = turn
    for _ in range(50):
        rows = db.fetch_all("SELECT parent_turn FROM agent_turns WHERE id = ?", (current,))
        if not rows or not rows[0]["parent_turn"]:
            return current
        current = int(rows[0]["parent_turn"])
    return current


def _window(db: Database, row: Any) -> tuple[str, str]:
    """When a run's own steps happened: from its start to the next run in the same chat."""
    following = db.fetch_all(
        "SELECT created FROM agent_turns WHERE session = ? AND id > ? ORDER BY id LIMIT 1",
        (row["session"], row["id"]),
    )
    return row["created"] or "", following[0]["created"] if following else "9999"


def _run(db: Database, row: Any, budget: list[int]) -> RunSpan:
    agent = (
        row["agent"]
        or db.fetch_all("SELECT agent FROM agent_sessions WHERE id = ?", (row["session"],))[0][
            "agent"
        ]
    )
    start, end = _window(db, row)
    children: list[RunSpan] = []
    calls = db.fetch_all(
        "SELECT id, time, model, status, input_tokens + output_tokens AS tokens FROM model_calls"
        " WHERE session = ? AND time >= ? AND time < ? ORDER BY id",
        (row["session"], start, end),
    )
    tools = db.fetch_all(
        "SELECT id, tool, status, started, result FROM tool_calls WHERE session = ? AND started >= ?"
        " AND started < ? ORDER BY id",
        (row["session"], start, end),
    )
    loads = db.fetch_all(
        "SELECT id, skill, time FROM skill_loads WHERE turn = ? ORDER BY id", (row["id"],)
    )
    given = db.fetch_all(
        "SELECT id, owner, objective, created, state FROM team_tasks WHERE assigner_turn = ?"
        " ORDER BY id",
        (row["id"],),
    )
    steps: list[tuple[str, RunSpan]] = []
    for call in calls:
        steps.append(
            (
                call["time"],
                RunSpan(
                    kind="model",
                    id=f"model-{call['id']}",
                    name=call["model"],
                    time=call["time"],
                    status=call["status"],
                    tokens=int(call["tokens"] or 0),
                ),
            )
        )
    for call in tools:
        steps.append(
            (
                call["started"],
                RunSpan(
                    kind="tool",
                    id=f"tool-{call['id']}",
                    name=call["tool"],
                    time=call["started"],
                    status=call["status"],
                    detail=(call["result"] or "")[:200] or None,
                ),
            )
        )
    for load in loads:
        steps.append(
            (
                load["time"],
                RunSpan(
                    kind="skill", id=f"skill-{load['id']}", name=load["skill"], time=load["time"]
                ),
            )
        )
    for task in given:
        steps.append(
            (
                task["created"],
                RunSpan(
                    kind="message",
                    id=f"task-{task['id']}",
                    name=f"Gave task {task['id']} to {cards.name(db, task['owner'])}",
                    agent=agent,
                    time=task["created"],
                    status=task["state"],
                    detail=task["objective"],
                ),
            )
        )
    for _, span in sorted(steps, key=lambda item: item[0]):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        children.append(span)
    for child in db.fetch_all(
        "SELECT * FROM agent_turns WHERE parent_turn = ? ORDER BY id", (row["id"],)
    ):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        children.append(_run(db, child, budget))
    status = row["failure"] or ("done" if row["closed"] else "running")
    return RunSpan(
        kind="run",
        id=f"run-{row['id']}",
        name=f"{cards.name(db, agent)}: {(row['text'] or '').strip()[:120]}",
        agent=agent,
        time=row["created"] or "",
        status=status,
        detail=row["cause"],
        tokens=sum(int(call["tokens"] or 0) for call in calls),
        children=children,
    )


def run_tree(ctx: Context, turn: int) -> RunSpan:
    db = ctx.bus.db
    root = _root(db, turn)
    rows = db.fetch_all("SELECT * FROM agent_turns WHERE id = ?", (root,))
    if not rows:
        raise CommandError("run.not_found", "That run no longer exists.", 404)
    return _run(db, rows[0], [MOST_SPANS])


def recent_runs(ctx: Context, limit: int) -> list[RunSpan]:
    """Runs that weren't started by another run, newest first, each with its own totals."""
    db = ctx.bus.db
    found = []
    for row in db.fetch_all(
        "SELECT * FROM agent_turns WHERE parent_turn IS NULL ORDER BY id DESC LIMIT ?", (limit,)
    ):
        span = _run(db, row, [MOST_SPANS])
        found.append(span.model_copy(update={"children": []}))
    return found
