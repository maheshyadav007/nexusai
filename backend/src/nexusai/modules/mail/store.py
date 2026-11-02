"""The mail database: one record per message, grouped into threads. Threads are the unit of work."""

import json
import re
import sqlite3
import unicodedata
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from nexusai.contracts.mail import (
    AttachmentView,
    MailFolderRef,
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


def sync_settings(db: Database, account: str) -> sqlite3.Row | None:
    """How this account is set to download, and how its last check went."""
    rows = db.fetch_all("SELECT * FROM mail_sync_settings WHERE account = ?", (account,))
    return rows[0] if rows else None


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
    ),
    Migration(
        "mail_messages_date_001",
        "CREATE INDEX messages_date ON messages (account, date DESC);",
    ),
    Migration(
        "mail_categories_001",
        """
CREATE TABLE mail_categories (
  name TEXT PRIMARY KEY, source TEXT NOT NULL, in_priority INTEGER NOT NULL DEFAULT 0,
  proposed INTEGER NOT NULL DEFAULT 0, why TEXT, sender TEXT, subject TEXT, created TEXT NOT NULL);
CREATE INDEX threads_date ON threads (account, last_date DESC, id DESC);
CREATE INDEX threads_category ON threads (account, category, last_date DESC, id DESC);
""",
    ),
    Migration(
        "mail_categories_order_001",
        """
ALTER TABLE mail_categories ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mail_categories ADD COLUMN updated TEXT;
""",
    ),
    Migration(
        "mail_sync_settings_001",
        """
CREATE TABLE mail_sync_settings (
  account TEXT PRIMARY KEY, pull_limit INTEGER, paused INTEGER NOT NULL DEFAULT 0, server_total INTEGER NOT NULL DEFAULT 0,
  last_check TEXT, last_found INTEGER NOT NULL DEFAULT 0, last_pulled INTEGER NOT NULL DEFAULT 0, last_found_at TEXT);
""",
    ),
    Migration(
        "mail_locations_001",
        """
CREATE TABLE message_locations (
  message INTEGER NOT NULL, account TEXT NOT NULL, folder TEXT NOT NULL, role TEXT NOT NULL, uid INTEGER NOT NULL,
  PRIMARY KEY (account, folder, uid));
CREATE INDEX message_locations_message ON message_locations (message);
INSERT INTO message_locations (message, account, folder, role, uid)
  SELECT id, account, folder, folder_role, uid FROM messages;
ALTER TABLE mail_folders ADD COLUMN server_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mail_folders ADD COLUMN server_unseen INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mail_folders ADD COLUMN uid_next INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mail_folders ADD COLUMN history_more INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mail_folders ADD COLUMN copies_below INTEGER;
ALTER TABLE threads ADD COLUMN in_junk INTEGER NOT NULL DEFAULT 0;
ALTER TABLE threads ADD COLUMN extra_categories TEXT NOT NULL DEFAULT '[]';
ALTER TABLE mail_sync_settings ADD COLUMN history_budget INTEGER;
ALTER TABLE mail_sync_settings ADD COLUMN never_delete INTEGER NOT NULL DEFAULT 1;
ALTER TABLE mail_sync_settings ADD COLUMN history_finished TEXT;
UPDATE mail_sync_settings SET history_budget = MAX(0, pull_limit - (SELECT COUNT(*) FROM messages m WHERE m.account = mail_sync_settings.account)) WHERE pull_limit IS NOT NULL;
UPDATE mail_sync_settings SET history_budget = 0, paused = 0 WHERE paused = 1;
ALTER TABLE mail_sync_settings DROP COLUMN pull_limit;
""",
    ),
    Migration(
        "mail_kinds_001",
        """
UPDATE threads SET category = 'Updates' WHERE category = 'Automated';
UPDATE threads SET category = 'Promotions' WHERE category = 'Newsletters';
UPDATE mail_categories SET name = 'Updates' WHERE name = 'Automated' AND NOT EXISTS (SELECT 1 FROM mail_categories WHERE name = 'Updates');
UPDATE mail_categories SET name = 'Promotions' WHERE name = 'Newsletters' AND NOT EXISTS (SELECT 1 FROM mail_categories WHERE name = 'Promotions');
""",
    ),
    Migration(
        "mail_images_001",
        """
CREATE TABLE mail_image_senders (address TEXT PRIMARY KEY, allow INTEGER NOT NULL);
UPDATE message_parts SET kind = 'signature' WHERE content_type LIKE 'image/%' AND kind IN ('inline', 'attachment') AND (
  size < 30000
  OR sha256 IN (SELECT sha256 FROM image_hashes WHERE seen >= 3)
  OR (size < 200000 AND (LOWER(filename) GLOB 'image[0-9]*.*' OR LOWER(filename) GLOB 'image.*' OR LOWER(filename) GLOB 'outlook-*' OR LOWER(filename) GLOB 'logo*' OR LOWER(filename) GLOB 'banner*' OR LOWER(filename) GLOB 'signature*' OR LOWER(filename) GLOB 'footer*')));
UPDATE message_parts SET kind = 'signature' WHERE kind = 'attachment' AND (content_type LIKE 'multipart/%' OR ((filename = '' OR filename = 'attachment') AND content_type IN ('text/x-amp-html', 'text/html', 'text/plain')));
UPDATE messages SET has_attachments = EXISTS (SELECT 1 FROM message_parts p WHERE p.message = messages.id AND p.kind IN ('attachment', 'calendar', 'risky'));
UPDATE threads SET has_attachments = EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = threads.id AND m.has_attachments = 1);
""",
    ),
]
ATTACHMENTS_FROM_PARTS = (
    "UPDATE messages SET has_attachments = EXISTS (SELECT 1 FROM message_parts p WHERE p.message = ?"
    " AND p.kind IN ('attachment', 'calendar', 'risky')) WHERE id = ?"
)
THREAD_COLUMNS = {"inbox": "in_inbox", "sent": "in_sent", "drafts": "in_drafts", "trash": "in_trash", "archive": "in_archive", "other": "in_other", "junk": "in_junk"}  # fmt: skip
# Which of an email's folders speaks for it, when something needs just one.
ROLE_RANK = {
    role: index
    for index, role in enumerate(
        ("inbox", "sent", "drafts", "other", "archive", "all", "junk", "trash")
    )
}
# Mail only in these stays in its own folder: no agent, search or Documents sees it.
SET_APART = ("junk", "trash")
FOLDER_FILTERS = {
    **{name: f"{column} = 1" for name, column in THREAD_COLUMNS.items()},
    # What came in, wherever it's been filed since.
    "all": "(in_inbox = 1 OR in_archive = 1)",
    # What needs attention: judged important, waiting on the person, in a category they marked,
    # or not judged yet, so nothing is hidden just because no model has looked at it.
    "priority": (
        "(in_inbox = 1 AND (importance = 'high' OR status = 'waiting_on_you'"
        " OR (category IS NULL AND importance != 'low')"
        " OR category IN (SELECT name FROM mail_categories WHERE in_priority = 1)))"
    ),
}
SUBJECT_WINDOW_DAYS = 30
# How many of the newest matches get ranked, and how many of those can become results.
SEARCH_RANKED = 5000
SEARCH_CANDIDATES = 2000
# The usual constant for reciprocal rank fusion: it keeps one list's top result from dominating.
FUSION_K = 60
EXCERPT_WORDS = 24
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
    roles = {
        row[0]
        for row in tx.execute(
            "SELECT DISTINCT l.role FROM message_locations l JOIN messages m ON m.id = l.message"
            " WHERE m.thread_id = ?",
            (thread,),
        )
    }
    # On Gmail, what's filed nowhere but All Mail is what the person archived.
    if "all" in roles and not roles & {"inbox", "sent", "drafts"}:
        roles.add("archive")
    people: list[str] = []
    for row in rows:
        seen[row["message_id"]] = seen.get(row["message_id"], True) and bool(row["read"])
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
    """None if this email is already stored, in which case it just gains this folder."""
    if tx.execute(
        "SELECT 1 FROM message_locations WHERE account = ? AND folder = ? AND uid = ?",
        (account, folder, uid),
    ).fetchone():
        return None
    held = find_message(tx, account, parsed.message_id)
    if held is not None:
        add_location(tx, held, account, folder, role, uid)
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
        kinds.append((part, classify(part, seen, config, parsed.html)))
        # Seen often enough to be a logo, so copies filed before this one were too.
        if seen == config.signature_repeat_count:
            _mark_repeats_as_logos(tx, part.sha256)
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
        "INSERT INTO message_locations (message, account, folder, role, uid) VALUES (?, ?, ?, ?, ?)",
        (message, account, folder, role, uid),
    )
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


def _mark_repeats_as_logos(tx: sqlite3.Connection, sha256: str) -> None:
    rows = tx.execute(
        "SELECT DISTINCT message FROM message_parts WHERE sha256 = ? AND kind IN ('inline', 'attachment')",
        (sha256,),
    ).fetchall()
    tx.execute(
        "UPDATE message_parts SET kind = 'signature' WHERE sha256 = ? AND kind IN ('inline', 'attachment')",
        (sha256,),
    )
    for row in rows:
        tx.execute(ATTACHMENTS_FROM_PARTS, (row["message"], row["message"]))
        thread = tx.execute(
            "SELECT thread_id FROM messages WHERE id = ?", (row["message"],)
        ).fetchone()
        if thread:
            refresh_thread(tx, thread[0])


def find_message(tx: sqlite3.Connection, account: str, message_id: str) -> int | None:
    row = tx.execute(
        "SELECT id FROM messages WHERE account = ? AND message_id = ? ORDER BY id LIMIT 1",
        (account, message_id),
    ).fetchone()
    return int(row[0]) if row else None


def _settle_primary(tx: sqlite3.Connection, message: int) -> None:
    """Keeps the columns on messages pointing at the folder that best speaks for this email."""
    rows = tx.execute(
        "SELECT folder, role, uid FROM message_locations WHERE message = ?", (message,)
    ).fetchall()
    if not rows:
        return
    best = min(rows, key=lambda row: ROLE_RANK.get(row["role"], ROLE_RANK["other"]))
    tx.execute(
        "UPDATE messages SET folder = ?, folder_role = ?, uid = ? WHERE id = ?",
        (best["folder"], best["role"], best["uid"], message),
    )


def add_location(
    tx: sqlite3.Connection, message: int, account: str, folder: str, role: str, uid: int
) -> None:
    tx.execute(
        "INSERT OR IGNORE INTO message_locations (message, account, folder, role, uid)"
        " VALUES (?, ?, ?, ?, ?)",
        (message, account, folder, role, uid),
    )
    _settle_primary(tx, message)
    row = tx.execute("SELECT thread_id FROM messages WHERE id = ?", (message,)).fetchone()
    if row:
        refresh_thread(tx, row[0])


def remove_location(tx: sqlite3.Connection, account: str, folder: str, uid: int) -> None:
    """Gone from one folder. The email itself goes only when this was its last."""
    row = tx.execute(
        "SELECT message FROM message_locations WHERE account = ? AND folder = ? AND uid = ?",
        (account, folder, uid),
    ).fetchone()
    if row is None:
        return
    message = row[0]
    tx.execute(
        "DELETE FROM message_locations WHERE account = ? AND folder = ? AND uid = ?",
        (account, folder, uid),
    )
    if tx.execute("SELECT 1 FROM message_locations WHERE message = ?", (message,)).fetchone():
        _settle_primary(tx, message)
        thread = tx.execute("SELECT thread_id FROM messages WHERE id = ?", (message,)).fetchone()
        if thread:
            refresh_thread(tx, thread[0])
        return
    remove_message(tx, message)


def locations_of(db_or_tx: Database | sqlite3.Connection, message: int) -> list[sqlite3.Row]:
    sql = "SELECT folder, role, uid FROM message_locations WHERE message = ?"
    if isinstance(db_or_tx, Database):
        return db_or_tx.fetch_all(sql, (message,))
    return db_or_tx.execute(sql, (message,)).fetchall()


def remove_message(tx: sqlite3.Connection, message: int) -> None:
    row = tx.execute("SELECT thread_id FROM messages WHERE id = ?", (message,)).fetchone()
    if row is None:
        return
    for statement in (
        "DELETE FROM message_locations WHERE message = ?",
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
        extra_categories=json.loads(row["extra_categories"]),
        why=row["why"],
        status=row["status"],
        importance=row["importance"],
        sender_name=row["sender_name"] if "sender_name" in row.keys() else None,  # noqa: SIM118
    )


# One conversation can be in several categories, and the first is the one Priority goes by.
IN_CATEGORY = "(category = ? OR EXISTS (SELECT 1 FROM json_each(extra_categories) WHERE value = ?))"
IN_LOCATION = (
    "id IN (SELECT m.thread_id FROM message_locations l JOIN messages m ON m.id = l.message"
    " WHERE l.account = ? AND l.folder = ?)"
)


def list_threads(
    db: Database,
    account: str,
    folder: str,
    category: str | None,
    before: str | None,
    limit: int,
    location: str | None = None,
) -> ThreadList:
    # A folder on the server is asked for by name, and the rest go by what kind of folder it is.
    where = ["account = ?", IN_LOCATION if location else FOLDER_FILTERS[folder]]
    params: list[object] = [account, account, location] if location else [account]
    if category:
        where.append(IN_CATEGORY)
        params += [category, category]
    if before:
        date, _, identifier = before.rpartition("|")
        where.append("(last_date, id) < (?, ?)")
        params += [date, int(identifier)]
    rows = db.fetch_all(
        "SELECT *, (SELECT COALESCE(NULLIF(m.from_name, ''), m.from_addr) FROM messages m"  # noqa: S608
        " WHERE m.thread_id = threads.id ORDER BY m.date DESC LIMIT 1) AS sender_name"
        f" FROM threads WHERE {' AND '.join(where)}"
        " ORDER BY last_date DESC, id DESC LIMIT ?",
        (*params, limit + 1),
    )
    page = rows[:limit]
    categories = db.fetch_all(
        f"SELECT DISTINCT category FROM threads WHERE account = ? AND {FOLDER_FILTERS[folder]}"  # noqa: S608
        " AND category IS NOT NULL ORDER BY category",
        (account,),
    )
    return ThreadList(
        threads=[row_of(row) for row in page],
        next_before=f"{page[-1]['last_date']}|{page[-1]['id']}" if len(rows) > limit else None,
        categories=[row["category"] for row in categories],
    )


def unread_counts(db: Database, account: str) -> dict[str, int]:
    return {
        name: int(
            db.fetch_all(
                f"SELECT COUNT(*) AS n FROM threads WHERE account = ? AND unread_count > 0 AND {where}",  # noqa: S608
                (account,),
            )[0]["n"]
        )
        for name, where in FOLDER_FILTERS.items()
    }


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


def show_images(db: Database, sender: str, default: str) -> bool:
    """The person's choice for this sender, or else their general setting."""
    rows = db.fetch_all("SELECT allow FROM mail_image_senders WHERE address = ?", (sender.lower(),))
    return bool(rows[0]["allow"]) if rows else default != "block"


def thread_view(db: Database, thread: int, remote_images: str = "load") -> ThreadView | None:
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
                show_images=show_images(db, message["from_addr"], remote_images),
                folders=[
                    MailFolderRef(name=row["folder"], role=row["role"])
                    for row in locations_of(db, message["id"])
                ],
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


def _search_words(text: str) -> list[str]:
    return [_folded(word) for word in re.findall(r"\w+", text, flags=re.UNICODE)]


def _fts_query(words: list[str], sender: str | None) -> str:
    """Each word as a quoted prefix, so punctuation in a search can't break it."""
    terms = [f'"{word}"*' for word in words]
    terms += [f'sender : "{word}"*' for word in _search_words(sender or "")]
    return " ".join(terms)


def _ranked_matches(
    db: Database, match: str, conditions: list[str], params: list[object], *, by_relevance: bool
) -> list[sqlite3.Row]:
    """Ranks only the newest matches. Ranking every match of a common word takes many seconds.

    A word in most of the mailbox has more matches than anyone reads, and its newest ones are
    the likeliest to matter. Narrowing the search reaches further back.
    """
    # Forcing this join order lets the index walk newest-first and stop early.
    source = (
        "mail_search CROSS JOIN messages m ON m.id = mail_search.rowid"
        " CROSS JOIN threads t ON t.id = m.thread_id"
    )
    where = ["mail_search MATCH ?", *conditions]
    values = [match, *params]
    if not by_relevance:
        # Only a person to look for, so there are no words to rank: newest first.
        return db.fetch_all(
            f"SELECT m.id AS message, m.thread_id AS thread FROM {source}"  # noqa: S608
            f" WHERE {' AND '.join(where)} ORDER BY mail_search.rowid DESC LIMIT ?",
            (*values, SEARCH_CANDIDATES),
        )
    floor = db.fetch_all(
        f"SELECT mail_search.rowid AS id FROM {source} WHERE {' AND '.join(where)}"  # noqa: S608
        " ORDER BY mail_search.rowid DESC LIMIT 1 OFFSET ?",
        (*values, SEARCH_RANKED - 1),
    )
    if floor:
        where.append("mail_search.rowid >= ?")
        values.append(floor[0]["id"])
    return db.fetch_all(
        f"SELECT m.id AS message, m.thread_id AS thread FROM {source}"  # noqa: S608
        f" WHERE {' AND '.join(where)} ORDER BY bm25(mail_search) LIMIT ?",
        (*values, SEARCH_CANDIDATES),
    )


def _folded(text: str) -> str:
    """The same folding the search index uses, so a match here is a match there."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _first_match(text: str, words: list[str]) -> re.Match[str] | None:
    return next(
        (m for m in re.finditer(r"\w+", text) if _folded(m.group()).startswith(tuple(words))),
        None,
    )


def _excerpt(text: str, words: list[str]) -> str:
    """Some words around the first match."""
    found = _first_match(text, words)
    centre = found.start() if found else 0
    tokens = list(re.finditer(r"\S+", text))
    position = next((i for i, token in enumerate(tokens) if token.end() > centre), 0)
    first = max(0, position - EXCERPT_WORDS // 2)
    shown = tokens[first : first + EXCERPT_WORDS]
    body = " ".join(token.group() for token in shown)
    return f"{'…' if first else ''}{body}{'…' if first + EXCERPT_WORDS < len(tokens) else ''}"


def _excerpts(db: Database, words: list[str], messages: list[int]) -> dict[int, tuple[str, bool]]:
    """Written here because FTS5's snippet() re-runs a prefix search for each row, taking seconds."""
    if not messages:
        return {}
    marks = ",".join("?" * len(messages))
    rows = db.fetch_all(
        f"SELECT rowid AS id, body, attachments FROM mail_search WHERE rowid IN ({marks})",  # noqa: S608
        messages,
    )
    return {
        row["id"]: (
            _excerpt(row["body"] or row["attachments"] or "", words),
            _first_match(row["attachments"] or "", words) is not None,
        )
        for row in rows
    }


def search(db: Database, account: str, query: SearchMail) -> SearchResults:
    conditions = ["m.account = ?"]
    params: list[object] = [account]
    words = _search_words(query.query)
    match = _fts_query(words, query.sender)
    if query.date_from:
        conditions.append("m.date >= ?")
        params.append(query.date_from)
    if query.date_to:
        conditions.append("m.date <= ?")
        params.append(query.date_to)
    if query.category:
        conditions.append(
            "(t.category = ? OR EXISTS (SELECT 1 FROM json_each(t.extra_categories) WHERE value = ?))"
        )
        params += [query.category, query.category]
    if query.has_attachment is not None:
        conditions.append("m.has_attachments = ?")
        params.append(int(query.has_attachment))
    if query.folder:
        conditions.append(
            "EXISTS (SELECT 1 FROM message_locations l WHERE l.message = m.id AND l.role = ?)"
        )
        params.append(query.folder)
    else:
        conditions.append(f"m.folder_role NOT IN {SET_APART}")
    if query.location:
        conditions.append(
            "EXISTS (SELECT 1 FROM message_locations l WHERE l.message = m.id AND l.folder = ?)"
        )
        params.append(query.location)
    if match:
        rows = _ranked_matches(db, match, conditions, params, by_relevance=bool(words))
    else:
        rows = db.fetch_all(
            "SELECT m.id AS message, m.thread_id AS thread FROM messages m"  # noqa: S608
            f" JOIN threads t ON t.id = m.thread_id WHERE {' AND '.join(conditions)}"
            " ORDER BY m.date DESC LIMIT ?",
            (*params, SEARCH_CANDIDATES),
        )
    # A conversation shows once, at its best match.
    chosen: dict[int, int] = {}
    for row in rows:
        chosen.setdefault(row["thread"], row["message"])
        if len(chosen) >= query.limit:
            break
    excerpts = _excerpts(db, words, list(chosen.values())) if words else {}
    snippets = (
        {}
        if words or not chosen
        else {
            row["id"]: row["snippet"]
            for row in db.fetch_all(
                f"SELECT id, snippet FROM messages WHERE id IN ({','.join('?' * len(chosen))})",  # noqa: S608
                list(chosen.values()),
            )
        }
    )
    hits: list[SearchHit] = []
    for thread_id, message in chosen.items():
        thread = db.fetch_all("SELECT * FROM threads WHERE id = ?", (thread_id,))[0]
        found = excerpts.get(message)
        hits.append(
            SearchHit(
                thread=row_of(thread),
                message_id=message,
                excerpt=found[0] if found else snippets.get(message, ""),
                matched_attachment=bool(found and found[1]),
            )
        )
    return SearchResults(hits=hits)


def merge_meaning(
    db: Database,
    account: str,
    query: SearchMail,
    words: SearchResults,
    meaning: list[tuple[int, str]],
) -> SearchResults:
    """Ranks by both lists together, so a good match in either comes up, and in both comes first."""
    if not meaning:
        return words
    conditions = ["m.account = ?"]
    params: list[object] = [account]
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
        conditions.append(
            "(t.category = ? OR EXISTS (SELECT 1 FROM json_each(t.extra_categories) WHERE value = ?))"
        )
        params += [query.category, query.category]
    if query.has_attachment is not None:
        conditions.append("m.has_attachments = ?")
        params.append(int(query.has_attachment))
    if query.folder:
        conditions.append(
            "EXISTS (SELECT 1 FROM message_locations l WHERE l.message = m.id AND l.role = ?)"
        )
        params.append(query.folder)
    else:
        conditions.append(f"m.folder_role NOT IN {SET_APART}")
    if query.location:
        conditions.append(
            "EXISTS (SELECT 1 FROM message_locations l WHERE l.message = m.id AND l.folder = ?)"
        )
        params.append(query.location)
    excerpts = dict(meaning)
    marks = ",".join("?" * len(excerpts))
    rows = db.fetch_all(
        f"SELECT m.id AS message, m.thread_id AS thread FROM messages m JOIN threads t ON t.id = m.thread_id"  # noqa: S608
        f" WHERE m.id IN ({marks}) AND {' AND '.join(conditions)}",
        (*excerpts, *params),
    )
    allowed = {row["message"]: row["thread"] for row in rows}
    scores: dict[int, float] = {}
    hits: dict[int, SearchHit] = {}
    for rank, hit in enumerate(words.hits):
        scores[hit.thread.id] = 1 / (FUSION_K + rank)
        hits[hit.thread.id] = hit
    seen: set[int] = set()
    rank = 0
    for message, excerpt in meaning:
        thread_id = allowed.get(message)
        if thread_id is None or thread_id in seen:
            continue
        seen.add(thread_id)
        scores[thread_id] = scores.get(thread_id, 0.0) + 1 / (FUSION_K + rank)
        rank += 1
        if thread_id in hits:
            hits[thread_id] = hits[thread_id].model_copy(update={"matched_by": "both"})
        else:
            thread = db.fetch_all("SELECT * FROM threads WHERE id = ?", (thread_id,))[0]
            hits[thread_id] = SearchHit(
                thread=row_of(thread),
                message_id=message,
                excerpt=excerpt,
                matched_attachment=False,
                matched_by="meaning",
            )
    ranked = sorted(hits, key=lambda thread_id: scores[thread_id], reverse=True)
    return SearchResults(hits=[hits[thread_id] for thread_id in ranked[: query.limit]])


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
