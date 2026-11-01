"""The mail database: one record per message, grouped into threads. Threads are the unit of work."""

import json
import re
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from nexusai.contracts.mail import (
    AttachmentView,
    MessageView,
    SearchHit,
    SearchMail,
    SearchResults,
    ThreadList,
    ThreadRow,
    ThreadView,
)
from nexusai.kernel.config import MailConfig
from nexusai.kernel.database import Database, Migration
from nexusai.modules.mail.attachments import classify
from nexusai.modules.mail.parse import (
    ParsedMessage,
    Part,
    normalize_subject,
    part_bytes,
)
from nexusai.modules.mail.rules import RuleMatch
from nexusai.modules.mail.safe_html import sanitize

MIGRATIONS = [
    Migration(
        "mail_001",
        """
CREATE TABLE mail_folders (
  account TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL, uidvalidity INTEGER,
  last_uid INTEGER NOT NULL DEFAULT 0, backfill_below INTEGER, PRIMARY KEY (account, name));
CREATE TABLE threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, subject TEXT NOT NULL,
  subject_norm TEXT NOT NULL, root_index TEXT, last_date TEXT NOT NULL, snippet TEXT NOT NULL DEFAULT '',
  message_count INTEGER NOT NULL DEFAULT 0, unread_count INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0, has_attachments INTEGER NOT NULL DEFAULT 0,
  participants TEXT NOT NULL DEFAULT '[]', category TEXT, category_source TEXT, why TEXT,
  status TEXT NOT NULL DEFAULT 'none', importance TEXT NOT NULL DEFAULT 'normal',
  in_inbox INTEGER NOT NULL DEFAULT 0, in_sent INTEGER NOT NULL DEFAULT 0,
  in_drafts INTEGER NOT NULL DEFAULT 0, in_trash INTEGER NOT NULL DEFAULT 0,
  in_archive INTEGER NOT NULL DEFAULT 0, in_other INTEGER NOT NULL DEFAULT 0);
CREATE INDEX threads_inbox ON threads (account, in_inbox, last_date DESC, id DESC);
CREATE INDEX threads_sent ON threads (account, in_sent, last_date DESC, id DESC);
CREATE INDEX threads_archive ON threads (account, in_archive, last_date DESC, id DESC);
CREATE INDEX threads_subject ON threads (account, subject_norm, last_date DESC);
CREATE INDEX threads_root ON threads (account, root_index);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, folder TEXT NOT NULL,
  folder_role TEXT NOT NULL, uid INTEGER NOT NULL, message_id TEXT NOT NULL,
  thread_id INTEGER NOT NULL, subject TEXT NOT NULL, from_name TEXT NOT NULL, from_addr TEXT NOT NULL,
  to_json TEXT NOT NULL, cc_json TEXT NOT NULL, date TEXT NOT NULL, snippet TEXT NOT NULL,
  own_text TEXT NOT NULL, clean_text TEXT NOT NULL, text TEXT NOT NULL, html TEXT,
  read INTEGER NOT NULL, flagged INTEGER NOT NULL, encrypted TEXT, signed INTEGER NOT NULL,
  rule TEXT, why TEXT, has_attachments INTEGER NOT NULL DEFAULT 0, UNIQUE (account, folder, uid));
CREATE INDEX messages_thread ON messages (thread_id, date);
CREATE INDEX messages_id ON messages (account, message_id);
CREATE TABLE message_raw (message INTEGER PRIMARY KEY, data BLOB NOT NULL);
CREATE TABLE message_refs (ref TEXT NOT NULL, message INTEGER NOT NULL);
CREATE INDEX message_refs_ref ON message_refs (ref);
CREATE TABLE message_parts (
  message INTEGER NOT NULL, part_index INTEGER NOT NULL, filename TEXT NOT NULL,
  content_type TEXT NOT NULL, size INTEGER NOT NULL, content_id TEXT, disposition TEXT,
  sha256 TEXT NOT NULL, kind TEXT NOT NULL, text TEXT, PRIMARY KEY (message, part_index));
CREATE INDEX message_parts_kind ON message_parts (kind);
CREATE TABLE image_hashes (sha256 TEXT PRIMARY KEY, seen INTEGER NOT NULL);
CREATE TABLE mail_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, op TEXT NOT NULL,
  payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE mail_drafts (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL, updated TEXT NOT NULL);
CREATE VIRTUAL TABLE mail_search USING fts5(subject, sender, body, attachments, tokenize = 'unicode61');
""",
    )
]
THREAD_COLUMNS = {"inbox": "in_inbox", "sent": "in_sent", "drafts": "in_drafts", "trash": "in_trash", "archive": "in_archive", "other": "in_other"}  # fmt: skip
SUBJECT_WINDOW_DAYS = 30
REPLY_PREFIX = re.compile(
    r"^\s*(re|fw|fwd|aw|sv|antw|tr|rv|ref|답장|회신|전달)\s*(\[\d+\])?\s*[:：]", re.I
)


@dataclass(frozen=True)
class Stored:
    message: int
    thread: int
    rule: str | None
    skip_agent: bool
    notify: bool
    is_new_thread: bool


def _participants(parsed: ParsedMessage) -> set[str]:
    return {address for address in [parsed.from_addr, *parsed.to, *parsed.cc] if address}


def _merge(tx: sqlite3.Connection, keep: int, others: set[int]) -> None:
    for other in others - {keep}:
        tx.execute("UPDATE messages SET thread_id = ? WHERE thread_id = ?", (keep, other))
        tx.execute("DELETE FROM threads WHERE id = ?", (other,))


def _assign_thread(tx: sqlite3.Connection, account: str, parsed: ParsedMessage) -> tuple[int, bool]:
    """References, then Outlook's Thread-Index, then subject and people."""
    ids = list(
        {
            parsed.message_id,
            *parsed.references,
            *([parsed.in_reply_to] if parsed.in_reply_to else []),
        }
    )
    marks = ",".join("?" * len(ids))
    found = {
        row[0]
        for row in tx.execute(
            f"SELECT DISTINCT thread_id FROM messages WHERE account = ? AND message_id IN ({marks})",  # noqa: S608
            (account, *ids),
        )
    }
    # Children that arrived first: backfill and PST import can bring mail in any order.
    found |= {
        row[0]
        for row in tx.execute(
            "SELECT DISTINCT m.thread_id FROM message_refs r JOIN messages m ON m.id = r.message"
            " WHERE r.ref = ? AND m.account = ?",
            (parsed.message_id, account),
        )
    }
    if found:
        keep = min(found)
        _merge(tx, keep, found)
        return keep, False
    if parsed.thread_index_root:
        row = tx.execute(
            "SELECT id FROM threads WHERE account = ? AND root_index = ?",
            (account, parsed.thread_index_root),
        ).fetchone()
        if row:
            return row[0], False
    norm = normalize_subject(parsed.subject)
    if norm and REPLY_PREFIX.match(parsed.subject):
        since = (
            datetime.fromisoformat(parsed.date) - timedelta(days=SUBJECT_WINDOW_DAYS)
        ).isoformat()
        people = _participants(parsed)
        for row in tx.execute(
            "SELECT id, participants FROM threads WHERE account = ? AND subject_norm = ?"
            " AND last_date >= ? ORDER BY last_date DESC LIMIT 5",
            (account, norm, since),
        ):
            if people & set(json.loads(row[1])):
                return row[0], False
    cursor = tx.execute(
        "INSERT INTO threads (account, subject, subject_norm, root_index, last_date)"
        " VALUES (?, ?, ?, ?, ?)",
        (account, parsed.subject, norm, parsed.thread_index_root, parsed.date),
    )
    return int(cursor.lastrowid or 0), True


def refresh_thread(tx: sqlite3.Connection, thread: int) -> None:
    """Recounts a thread from its messages. The same mail in two folders counts once."""
    rows = tx.execute(
        "SELECT message_id, folder_role, read, flagged, date, snippet, subject, from_addr, to_json,"
        " cc_json, has_attachments FROM messages WHERE thread_id = ? ORDER BY date",
        (thread,),
    ).fetchall()
    if not rows:
        tx.execute("DELETE FROM threads WHERE id = ?", (thread,))
        return
    seen: dict[str, bool] = {}
    roles: set[str] = set()
    people: list[str] = []
    for row in rows:
        seen[row["message_id"]] = seen.get(row["message_id"], True) and bool(row["read"])
        roles.add(row["folder_role"])
        for address in [row["from_addr"], *json.loads(row["to_json"]), *json.loads(row["cc_json"])]:
            if address and address not in people:
                people.append(address)
    latest = rows[-1]
    columns = {column: int(role in roles) for role, column in THREAD_COLUMNS.items()}
    assignments = ", ".join(f"{column} = ?" for column in columns)
    tx.execute(
        f"UPDATE threads SET last_date = ?, snippet = ?, message_count = ?, unread_count = ?,"  # noqa: S608
        f" flagged = ?, has_attachments = ?, participants = ?, {assignments} WHERE id = ?",
        (
            latest["date"],
            latest["snippet"],
            len(seen),
            sum(1 for read in seen.values() if not read),
            int(any(row["flagged"] for row in rows)),
            int(any(row["has_attachments"] for row in rows)),
            json.dumps(people),
            *columns.values(),
            thread,
        ),
    )


def store_message(
    tx: sqlite3.Connection,
    *,
    account: str,
    folder: str,
    role: str,
    uid: int,
    raw: bytes,
    read: bool,
    flagged: bool,
    parsed: ParsedMessage,
    match: RuleMatch | None,
    config: MailConfig,
) -> Stored | None:
    """None if this copy is already stored."""
    if tx.execute(
        "SELECT 1 FROM messages WHERE account = ? AND folder = ? AND uid = ?",
        (account, folder, uid),
    ).fetchone():
        return None
    thread, is_new = _assign_thread(tx, account, parsed)
    kinds: list[tuple[Part, str]] = []
    for part in parsed.parts:
        seen = 0
        if part.content_type.startswith("image/"):
            tx.execute(
                "INSERT INTO image_hashes (sha256, seen) VALUES (?, 1)"
                " ON CONFLICT (sha256) DO UPDATE SET seen = seen + 1",
                (part.sha256,),
            )
            seen = tx.execute(
                "SELECT seen FROM image_hashes WHERE sha256 = ?", (part.sha256,)
            ).fetchone()[0]
        kinds.append((part, classify(part, seen, config)))
    has_attachments = any(kind in {"attachment", "calendar", "risky"} for _, kind in kinds)
    is_read = read or bool(match and match.actions.mark_read)
    cursor = tx.execute(
        "INSERT INTO messages (account, folder, folder_role, uid, message_id, thread_id, subject,"
        " from_name, from_addr, to_json, cc_json, date, snippet, own_text, clean_text, text, html,"
        " read, flagged, encrypted, signed, rule, why, has_attachments)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            account, folder, role, uid, parsed.message_id, thread, parsed.subject, parsed.from_name,
            parsed.from_addr, json.dumps(parsed.to), json.dumps(parsed.cc), parsed.date, parsed.snippet,
            parsed.own, parsed.clean, parsed.text, parsed.html, int(is_read), int(flagged),
            parsed.encrypted, int(parsed.signed), match.name if match else None,
            match.why if match else None, int(has_attachments),
        ),
    )  # fmt: skip
    message = int(cursor.lastrowid or 0)
    tx.execute(
        "INSERT INTO message_raw (message, data) VALUES (?, ?)", (message, zlib.compress(raw))
    )
    for ref in {*parsed.references, *([parsed.in_reply_to] if parsed.in_reply_to else [])}:
        tx.execute("INSERT INTO message_refs (ref, message) VALUES (?, ?)", (ref, message))
    for part, kind in kinds:
        tx.execute(
            "INSERT INTO message_parts (message, part_index, filename, content_type, size, content_id,"
            " disposition, sha256, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (message, part.index, part.filename, part.content_type, part.size, part.content_id, part.disposition, part.sha256, kind),
        )  # fmt: skip
    # Only the message's own new text, so a search finds one hit per thread instead of every quote.
    tx.execute(
        "INSERT INTO mail_search (rowid, subject, sender, body, attachments) VALUES (?, ?, ?, ?, ?)",
        (message, parsed.subject, f"{parsed.from_name} {parsed.from_addr}", parsed.own, ""),
    )
    if match and match.actions.category:
        tx.execute(
            "UPDATE threads SET category = ?, category_source = 'rule', why = ?"
            " WHERE id = ? AND COALESCE(category_source, '') != 'user'",
            (match.actions.category, match.why, thread),
        )
    refresh_thread(tx, thread)
    return Stored(
        message=message,
        thread=thread,
        rule=match.name if match else None,
        skip_agent=bool(match and match.actions.skip_agent),
        notify=bool(match and match.actions.notify),
        is_new_thread=is_new,
    )


def remove_message(tx: sqlite3.Connection, message: int) -> None:
    row = tx.execute("SELECT thread_id FROM messages WHERE id = ?", (message,)).fetchone()
    if row is None:
        return
    for statement in (
        "DELETE FROM messages WHERE id = ?",
        "DELETE FROM message_raw WHERE message = ?",
        "DELETE FROM message_refs WHERE message = ?",
        "DELETE FROM message_parts WHERE message = ?",
        "DELETE FROM mail_search WHERE rowid = ?",
    ):
        tx.execute(statement, (message,))
    refresh_thread(tx, row[0])


def row_of(row: sqlite3.Row) -> ThreadRow:
    return ThreadRow(
        id=row["id"],
        subject=row["subject"],
        participants=json.loads(row["participants"]),
        last_date=row["last_date"],
        snippet=row["snippet"],
        message_count=row["message_count"],
        unread_count=row["unread_count"],
        flagged=bool(row["flagged"]),
        has_attachments=bool(row["has_attachments"]),
        category=row["category"],
        category_source=row["category_source"],
        why=row["why"],
        status=row["status"],
        importance=row["importance"],
    )


def list_threads(
    db: Database, account: str, folder: str, category: str | None, before: str | None, limit: int
) -> ThreadList:
    column = THREAD_COLUMNS[folder]
    where = ["account = ?", f"{column} = 1"]
    params: list[object] = [account]
    if category:
        where.append("category = ?")
        params.append(category)
    if before:
        date, _, identifier = before.rpartition("|")
        where.append("(last_date, id) < (?, ?)")
        params += [date, int(identifier)]
    rows = db.fetch_all(
        f"SELECT * FROM threads WHERE {' AND '.join(where)}"  # noqa: S608
        " ORDER BY last_date DESC, id DESC LIMIT ?",
        (*params, limit + 1),
    )
    page = rows[:limit]
    categories = db.fetch_all(
        f"SELECT DISTINCT category FROM threads WHERE account = ? AND {column} = 1"  # noqa: S608
        " AND category IS NOT NULL ORDER BY category",
        (account,),
    )
    return ThreadList(
        threads=[row_of(row) for row in page],
        next_before=f"{page[-1]['last_date']}|{page[-1]['id']}" if len(rows) > limit else None,
        categories=[row["category"] for row in categories],
    )


def raw_of(db: Database, message: int) -> bytes | None:
    rows = db.fetch_all("SELECT data FROM message_raw WHERE message = ?", (message,))
    return zlib.decompress(rows[0]["data"]) if rows else None


def _safe_html(db: Database, row: sqlite3.Row) -> str | None:
    if not row["html"]:
        return None
    parts = db.fetch_all(
        "SELECT * FROM message_parts WHERE message = ? AND content_id IS NOT NULL", (row["id"],)
    )
    inline: list[tuple[Part, bytes]] = []
    raw = raw_of(db, row["id"]) if parts else None
    for part in parts:
        if raw is None or part["kind"] == "risky":
            continue
        found = part_bytes(raw, part["part_index"])
        if found:
            inline.append(
                (
                    Part(part["part_index"], part["filename"], part["content_type"], part["size"], part["content_id"], part["disposition"], part["sha256"]),
                    found[0],
                )
            )  # fmt: skip
    return sanitize(row["html"], inline)


def thread_view(db: Database, thread: int) -> ThreadView | None:
    rows = db.fetch_all("SELECT * FROM threads WHERE id = ?", (thread,))
    if not rows:
        return None
    messages = db.fetch_all(
        "SELECT * FROM messages WHERE thread_id = ? ORDER BY date, id", (thread,)
    )
    # The same mail can sit in two folders. Show one, preferring the inbox copy.
    best: dict[str, sqlite3.Row] = {}
    for message in messages:
        current = best.get(message["message_id"])
        if current is None or (
            message["folder_role"] == "inbox" and current["folder_role"] != "inbox"
        ):
            best[message["message_id"]] = message
    ordered = sorted(best.values(), key=lambda m: (m["date"], m["id"]))
    views: list[MessageView] = []
    previous: set[str] | None = None
    for message in ordered:
        to, cc = json.loads(message["to_json"]), json.loads(message["cc_json"])
        people = {message["from_addr"], *to, *cc}
        parts = db.fetch_all("SELECT * FROM message_parts WHERE message = ?", (message["id"],))
        views.append(
            MessageView(
                id=message["id"],
                subject=message["subject"],
                from_name=message["from_name"],
                from_addr=message["from_addr"],
                to=to,
                cc=cc,
                date=message["date"],
                own_text=message["own_text"],
                text=message["text"],
                html=_safe_html(db, message),
                read=bool(message["read"]),
                flagged=bool(message["flagged"]),
                folder=message["folder_role"] if message["folder_role"] in THREAD_COLUMNS else "other",
                encrypted=message["encrypted"],
                signed=bool(message["signed"]),
                why=message["why"],
                added=sorted(people - previous) if previous is not None else [],
                dropped=sorted(previous - people) if previous is not None else [],
                attachments=[
                    AttachmentView(index=p["part_index"], filename=p["filename"], content_type=p["content_type"], size=p["size"], kind=p["kind"])
                    for p in parts
                ],
                hidden_attachments=sum(1 for p in parts if p["kind"] == "signature"),
            )
        )  # fmt: skip
        previous = people
    return ThreadView(thread=row_of(rows[0]), messages=views)


def _fts_query(text: str) -> str:
    """Each word as a quoted prefix, so punctuation in a search can't break it."""
    words = re.findall(r"[\w@.+-]+", text, flags=re.UNICODE)
    return " ".join(f'"{word}"*' for word in words)


def search(db: Database, account: str, query: SearchMail) -> SearchResults:
    conditions = ["m.account = ?"]
    params: list[object] = [account]
    match = _fts_query(query.query)
    if match:
        conditions.append("mail_search MATCH ?")
        params.append(match)
    if query.sender:
        conditions.append("(m.from_addr LIKE ? OR m.from_name LIKE ?)")
        params += [f"%{query.sender}%", f"%{query.sender}%"]
    if query.date_from:
        conditions.append("m.date >= ?")
        params.append(query.date_from)
    if query.date_to:
        conditions.append("m.date <= ?")
        params.append(query.date_to)
    if query.category:
        conditions.append("t.category = ?")
        params.append(query.category)
    if query.has_attachment is not None:
        conditions.append("m.has_attachments = ?")
        params.append(int(query.has_attachment))
    if query.folder:
        conditions.append("m.folder_role = ?")
        params.append(query.folder)
    excerpt = "snippet(mail_search, -1, '', '', '…', 24)" if match else "m.snippet"
    order = "bm25(mail_search)" if match else "m.date DESC"
    join = "mail_search JOIN messages m ON m.id = mail_search.rowid" if match else "messages m"
    hit_attachments = "highlight(mail_search, 3, '\x01', '\x01')" if match else "''"
    rows = db.fetch_all(
        f"SELECT m.id AS message, m.thread_id AS thread, {excerpt} AS excerpt,"  # noqa: S608
        f" {hit_attachments} AS attachment_hit FROM {join} JOIN threads t ON t.id = m.thread_id"
        f" WHERE {' AND '.join(conditions)} ORDER BY {order} LIMIT 2000",
        params,
    )
    hits: list[SearchHit] = []
    seen: set[int] = set()
    for row in rows:
        if row["thread"] in seen:
            continue
        seen.add(row["thread"])
        thread = db.fetch_all("SELECT * FROM threads WHERE id = ?", (row["thread"],))[0]
        hits.append(
            SearchHit(
                thread=row_of(thread),
                message_id=row["message"],
                excerpt=row["excerpt"],
                matched_attachment="\x01" in (row["attachment_hit"] or ""),
            )
        )
        if len(hits) >= query.limit:
            break
    return SearchResults(hits=hits)


def attachment(db: Database, message: int, index: int) -> tuple[str, bytes, bool] | None:
    """The file's name, its bytes, and whether it's too risky to hand over."""
    rows = db.fetch_all(
        "SELECT filename, kind FROM message_parts WHERE message = ? AND part_index = ?",
        (message, index),
    )
    raw = raw_of(db, message) if rows else None
    found = part_bytes(raw, index) if raw else None
    if not rows or found is None:
        return None
    return rows[0]["filename"], found[0], rows[0]["kind"] == "risky"
