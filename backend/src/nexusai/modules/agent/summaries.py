"""Incremental summaries track source identity and bounded coverage, never message counts alone."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from nexusai.contracts.agent import ThreadSummary
from nexusai.kernel.database import Migration
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.agent import gateway, guard, prompts_builder, providers
from nexusai.modules.agent.prompt_data import untrusted

MIGRATION = Migration(
    "agent_summary_sources_001",
    "ALTER TABLE thread_summaries ADD COLUMN sources TEXT NOT NULL DEFAULT '{}';",
)


def _sources(ctx: Context, thread: int) -> list[dict[str, Any]]:
    rows = ctx.bus.db.fetch_all(
        "SELECT MIN(id) id,from_name,from_addr,date,subject,clean_text,encrypted FROM messages WHERE thread_id=? GROUP BY message_id ORDER BY date,id",
        (thread,),
    )
    sources = []
    for row in rows:
        body = "[Encrypted: content unavailable]" if row["encrypted"] else row["clean_text"]
        text = f"[message {row['id']}] From {row['from_name']} <{row['from_addr']}> on {row['date']}\nSubject: {row['subject']}\n{body}"
        sources.append(
            dict(
                id=str(row["id"]),
                text=text,
                digest=hashlib.sha256(text.encode()).hexdigest(),
                encrypted=bool(row["encrypted"]),
            )
        )
    return sources


def _state(ctx: Context, thread: int) -> tuple[list[dict[str, Any]], Any, dict[str, Any], bool]:
    sources = _sources(ctx, thread)
    rows = ctx.bus.db.fetch_all("SELECT * FROM thread_summaries WHERE thread=?", (thread,))
    row = rows[0] if rows else None
    previous = json.loads(row["sources"]) if row else {}
    current = {source["id"]: source for source in sources}
    changed = bool(
        row
        and (
            not previous
            or any(
                key not in current or value["digest"] != current[key]["digest"]
                for key, value in previous.items()
            )
        )
    )
    return sources, row, {} if changed else previous, changed


def view(ctx: Context, thread: int) -> ThreadSummary:
    sources, row, coverage, changed = _state(ctx, thread)
    covered = sum(
        1
        for source in sources
        if coverage.get(source["id"], {}).get("offset", 0) >= len(source["text"])
    )
    return ThreadSummary(
        thread=thread,
        text=row["text"] if row else None,
        covered=covered,
        new_messages=len(sources) - covered,
        updated=row["updated"] if row else None,
        partial=covered < len(sources) or any(source["encrypted"] for source in sources),
        changed=changed,
    )


def generate(ctx: Context, thread: int) -> ThreadSummary:
    sources, row, coverage, changed = _state(ctx, thread)
    if not sources:
        raise CommandError("thread.not_found", "That conversation no longer exists.", 404)
    if coverage and all(
        coverage.get(s["id"], {}).get("offset", 0) >= len(s["text"]) for s in sources
    ):
        return view(ctx, thread)
    baseline = {s["id"]: s["digest"] for s in sources}
    remaining = ctx.config.agent.max_thread_chars
    blocks = []
    for source in sources:
        offset = coverage.get(source["id"], {}).get("offset", 0)
        if offset >= len(source["text"]):
            continue
        chunk = source["text"][offset : offset + remaining]
        if not chunk:
            break
        blocks.append(
            f"Source message {source['id']}, characters {offset}–{offset + len(chunk)}:\n{chunk}"
        )
        coverage[source["id"]] = {"digest": source["digest"], "offset": offset + len(chunk)}
        remaining -= len(chunk)
        if remaining <= 0:
            break
    earlier = row["text"] if row and not changed else ""
    evidence = ""
    if earlier:
        evidence += (
            f"Earlier summary (source-derived data):\n{earlier}\n\nAdditional source chunks:\n"
        )
    evidence += "\n\n".join(blocks)
    task = (
        "Reconcile dates, negations, unresolved asks and commitments. Additional messages may be older than the earlier summary. Do not claim to have read omitted or encrypted content.\n"
        + untrusted(evidence)
    )
    layers = prompts_builder.build_layers(ctx.config, "summary")
    try:
        result = gateway.call_model(
            ctx,
            agent="summary",
            session=None,
            layers=layers,
            messages=[providers.Message("user", task)],
        )
    except (
        providers.ModelUnavailable,
        providers.ModelContextExceeded,
        providers.ModelResponseInvalid,
        providers.ModelNotConfigured,
        providers.ModelFlagged,
        gateway.DailyCapReached,
        guard.GuardBlocked,
    ) as error:
        raise CommandError("summary.failed", str(error), 502) from error
    if not result.text.strip():
        raise CommandError(
            "summary.empty", "No summary was produced. The previous summary is preserved.", 502
        )
    with ctx.bus.db.serialized():
        if baseline != {s["id"]: s["digest"] for s in _sources(ctx, thread)}:
            raise CommandError(
                "summary.changed",
                "The conversation changed while summarizing. Update again to include the latest version.",
                409,
            )
        covered = sum(coverage.get(s["id"], {}).get("offset", 0) >= len(s["text"]) for s in sources)
        with ctx.bus.unit_of_work() as work:
            work.tx.execute(
                "INSERT INTO thread_summaries(thread,text,covered,updated,sources) VALUES(?,?,?,?,?) ON CONFLICT(thread) DO UPDATE SET text=excluded.text,covered=excluded.covered,updated=excluded.updated,sources=excluded.sources",
                (
                    thread,
                    result.text.strip(),
                    covered,
                    datetime.now(UTC).isoformat(),
                    json.dumps(coverage),
                ),
            )
            work.emit("summary.ready", {"thread_id": thread}, source="agent", trace_id=ctx.trace_id)
    return view(ctx, thread)
