"""Saved live views over the app's data. Showing one never calls a model."""

import json

from nexusai.contracts.documents import ListDocuments
from nexusai.contracts.panels import (
    GetPanelBoard,
    GetPanelResults,
    Panel,
    PanelBoard,
    PanelFilters,
    PanelResults,
    ResetPanelBoard,
)
from nexusai.kernel.database import Migration
from nexusai.kernel.module import Context, Module
from nexusai.modules.documents.module import list_documents
from nexusai.modules.mail import accounts, store

panels_module = Module(
    name="panels",
    migrations=[
        Migration(
            "panels_001",
            "CREATE TABLE panel_board (id INTEGER PRIMARY KEY CHECK (id = 1), value TEXT NOT NULL)",
        )
    ],
)
STARTERS = [
    Panel(id="waiting-on-you", title="Waiting on you", source="threads", filters=PanelFilters(status="waiting_on_you"), size="medium"),
    Panel(id="unread", title="Unread", source="threads", filters=PanelFilters(unread_only=True), size="medium"),
    Panel(id="flagged", title="Flagged", source="threads", filters=PanelFilters(flagged_only=True), size="small"),
    Panel(id="recent-documents", title="Recent documents", source="documents", size="small"),
]  # fmt: skip


def _board(ctx: Context) -> PanelBoard:
    rows = ctx.bus.db.fetch_all("SELECT value FROM panel_board")
    return PanelBoard.model_validate_json(rows[0]["value"]) if rows else PanelBoard(panels=STARTERS)


def _save(ctx: Context, board: PanelBoard) -> PanelBoard:
    with ctx.bus.unit_of_work() as work:
        work.tx.execute(
            "INSERT INTO panel_board (id, value) VALUES (1, ?)"
            " ON CONFLICT (id) DO UPDATE SET value = excluded.value",
            (board.model_dump_json(),),
        )
        work.emit(
            "panels.changed", {"count": len(board.panels)}, source="panels", trace_id=ctx.trace_id
        )
    return board


@panels_module.query("panels.board")
def get_board(query: GetPanelBoard, ctx: Context) -> PanelBoard:
    return _board(ctx)


@panels_module.command("panels.saveBoard")
def save_board(command: PanelBoard, ctx: Context) -> PanelBoard:
    return _save(ctx, command)


@panels_module.command("panels.reset")
def reset_board(command: ResetPanelBoard, ctx: Context) -> PanelBoard:
    return _save(ctx, PanelBoard(panels=STARTERS))


def _thread_results(ctx: Context, filters: PanelFilters, limit: int) -> PanelResults:
    account = accounts.current_account(ctx.config)
    where = ["account = ?"]
    params: list[object] = [account]
    if filters.sender:
        where.append("participants LIKE ?")
        params.append(f"%{filters.sender.lower()}%")
    if filters.subject:
        where.append("subject LIKE ?")
        params.append(f"%{filters.subject}%")
    if filters.category:
        where.append("category = ?")
        params.append(filters.category)
    if filters.status:
        where.append("status = ?")
        params.append(filters.status)
    if filters.unread_only:
        where.append("unread_count > 0")
    if filters.flagged_only:
        where.append("flagged = 1")
    rows = ctx.bus.db.fetch_all(
        f"SELECT * FROM threads WHERE {' AND '.join(where)} ORDER BY last_date DESC, id DESC LIMIT ?",  # noqa: S608
        (*params, limit),
    )
    return PanelResults(threads=[store.row_of(row) for row in rows])


@panels_module.query("panels.results")
def get_results(query: GetPanelResults, ctx: Context) -> PanelResults:
    filters = query.panel.filters
    if query.panel.source == "threads":
        return _thread_results(ctx, filters, query.limit)
    if query.panel.source == "documents":
        documents = list_documents(
            ListDocuments(query=filters.query or "", folder=filters.folder, limit=query.limit), ctx
        )
        return PanelResults(documents=json.loads(documents.model_dump_json())["documents"])
    # Tasks and reminders join with the daily work stage.
    return PanelResults()
