"""Sort lab: try the mail grouping on a real mailbox, collect feedback, then forget the mail.

It runs on this computer only, uses no AI, and never changes the mail server: IMAP reads with
PEEK so nothing is marked read, and neither protocol is allowed to delete. Mail is kept in one
folder that finishing or discarding the experiment deletes, as does the next start.
"""

import contextlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from nexusai.contracts.mail import MailAuth, MailProfile, ServerSettings
from nexusai.kernel.home import app_data_dir
from nexusai.modules.mail import grouping, rules, sort_rules, sort_view
from nexusai.modules.mail.imap import Fetched, Folder, ImapSession, SignInFailed, synced_folders
from nexusai.modules.mail.parse import ParsedMessage, parse_message
from nexusai.modules.mail.pop3 import Pop3Session

BATCH = 50
SETTINGS_FILE = "sortlab.env"
# How many of the newest emails to read, unless NEXUSAI_SORTLAB_LIMIT says otherwise.
LIMIT = 15000
SKIPPED_ROLES = {"trash", "junk", "drafts"}
PAGE = Path(__file__).with_name("page.html")
# Beside the lab: the downloaded mail, deleted when an experiment ends, and the results kept.
MAIL_FOLDER = "sort-lab-mail"
RESULTS_FOLDER = "sort-lab-results"


class Session(Protocol):
    def folders(self) -> list[Folder]: ...
    def select(self, name: str) -> tuple[int, int]: ...
    def all_uids(self) -> list[int]: ...
    def fetch(self, uids: list[int]) -> list[Fetched]: ...
    def close(self) -> None: ...


class SignIn(BaseModel):
    """All a person types. Everything about the server comes from the settings file."""

    username: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class Server:
    host: str
    port: int
    protocol: Literal["imap", "pop3"]
    secure: bool
    verify_cert: bool
    domain: str
    limit: int
    source: str


class SenderChoice(BaseModel):
    """Where the person put one sender: the side the AI reads or ignores, and on the ignored
    side, whether it gets its own category and what it's called."""

    sender: str = Field(max_length=320)
    side: Literal["reads", "ignores"]
    own: bool = False
    name: str = Field(default="", max_length=200)


class LabCategory(BaseModel):
    name: str = Field(max_length=200)
    senders: list[str] = Field(default_factory=list, max_length=5000)


class Sorted(BaseModel):
    """The ignored side as the page has it: its own categories, and the senders going straight
    into Automated."""

    categories: list[LabCategory] = Field(default_factory=list, max_length=2000)
    automated: list[str] = Field(default_factory=list, max_length=20000)


class Finish(BaseModel):
    senders: list[SenderChoice] = Field(default_factory=list)
    sorted: Sorted = Field(default_factory=Sorted)
    details: bool = True


@dataclass
class Lab:
    folder: Path
    results: Path
    state: str = "idle"
    done: int = 0
    total: int = 0
    error: str = ""
    report: grouping.SenderReport | None = None
    # The downloaded mail, read once, for the rule engine to try each rule on.
    mail: list[ParsedMessage] = field(default_factory=list, repr=False)
    found: dict[str, Any] = field(default_factory=dict)
    # Show the results folder when an experiment finishes, so the file is easy to send.
    reveal: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def forget_mail(self) -> int:
        """Deletes every downloaded email. Returns how many there were."""
        count = len(list(self.folder.glob("*.eml"))) if self.folder.exists() else 0
        shutil.rmtree(self.folder, ignore_errors=True)
        self.report, self.found, self.mail = None, {}, []
        return count


def _beside_program() -> Path:
    """The folder of the double-clicked exe, or where the lab was started from."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def settings_files() -> list[Path]:
    """Where the server settings may be, first found first used: a sortlab.env beside the lab,
    a file named by NEXUSAI_ENV_FILE, then the NexusAI app's own company settings."""
    found = [_beside_program() / SETTINGS_FILE]
    if named := os.environ.get("NEXUSAI_ENV_FILE"):
        found.append(Path(named))
    base = app_data_dir().parent
    found += [base / name / "company.env" for name in ("NexusAI", "NexusAI Pilot")]
    return found


def server_settings() -> Server | None:
    """The company server, or None when no settings file names one."""
    for path in settings_files():
        if not path.is_file():
            continue
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, equals, value = line.strip().removeprefix("export ").partition("=")
            if equals and not key.strip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
        host = values.get("NEXUSAI_MAIL_HOST", "")
        if not host:
            continue
        on = {"1", "true", "yes", "on"}
        protocol = values.get("NEXUSAI_MAIL_PROTOCOL", "imap").strip().lower()
        protocol = protocol if protocol in {"imap", "pop3"} else "imap"
        return Server(
            host=host,
            port=int(values.get("NEXUSAI_MAIL_PORT", "995" if protocol == "pop3" else "993")),
            protocol=cast(Literal["imap", "pop3"], protocol),
            secure=values.get("NEXUSAI_MAIL_SECURE", "true").lower() in on,
            verify_cert=values.get("NEXUSAI_MAIL_VERIFY_CERT", "true").lower() in on,
            domain=values.get("NEXUSAI_MAIL_DOMAIN", "").strip().lstrip("@"),
            limit=int(values.get("NEXUSAI_SORTLAB_LIMIT", str(LIMIT))),
            source=str(path),
        )
    return None


def address_for(login: str, domain: str) -> str:
    """A login that isn't an address gets the company's domain."""
    return login if "@" in login or not domain else f"{login}@{domain}"


def open_session(sign_in: SignIn, server: Server) -> Session:
    login = sign_in.username.strip()
    address = address_for(login, server.domain)
    profile = MailProfile(
        label="Sort lab",
        protocol=server.protocol,
        imap=ServerSettings(
            host=server.host,
            port=server.port,
            secure=server.secure,
            verify_cert=server.verify_cert,
        ),
        smtp=ServerSettings(host=server.host, port=465),
        auth=MailAuth(user=login),
        address=address,
    )
    if server.protocol == "pop3":
        numbers: dict[str, int] = {}

        def uids(names: list[str]) -> dict[str, int]:
            for name in names:
                numbers.setdefault(name, len(numbers) + 1)
            return dict(numbers)

        return Pop3Session(profile, sign_in.password, 60, never_delete=True, uids=uids)
    return ImapSession(profile, sign_in.password, 60, never_delete=True)


def download(lab: Lab, sign_in: SignIn, server: Server) -> None:
    """Newest mail first, from every folder but trash, junk and drafts, up to the limit."""
    session: Session | None = None
    try:
        lab.state = "connecting"
        session = open_session(sign_in, server)
        plan: list[tuple[str, list[int]]] = []
        wanted = server.limit
        for folder in synced_folders(session.folders()):
            if folder.role in SKIPPED_ROLES or wanted <= 0:
                continue
            session.select(folder.name)
            uids = sorted(session.all_uids(), reverse=True)[:wanted]
            plan.append((folder.name, uids))
            wanted -= len(uids)
        lab.total, lab.done, lab.state = sum(len(uids) for _, uids in plan), 0, "downloading"
        lab.folder.mkdir(parents=True, exist_ok=True)
        for index, (name, uids) in enumerate(plan):
            session.select(name)
            for start in range(0, len(uids), BATCH):
                for item in session.fetch(uids[start : start + BATCH]):
                    (lab.folder / f"{index:03d}-{item.uid}.eml").write_bytes(item.raw)
                lab.done = min(lab.total, lab.done + len(uids[start : start + BATCH]))
        session.close()
        session = None
        lab.state = "grouping"
        downloaded = grouping.read_folder(lab.folder)
        lab.report = grouping.score_senders(downloaded)
        lab.mail = [parse_message(raw) for _, raw in downloaded]
        lab.found = describe(lab)
        lab.state = "ready"
    except SignInFailed:
        lab.state, lab.error = "failed", "The server refused the username or password."
    except Exception as error:
        lab.state, lab.error = "failed", f"{type(error).__name__}: {str(error)[:300]}"
    finally:
        if session is not None:
            with contextlib.suppress(Exception):
                session.close()


def describe(lab: Lab) -> dict[str, Any]:
    """Every sender with its score and side, the way the page shows it."""
    assert lab.report is not None
    return sort_view.describe_senders(lab.report, lambda key: (lab.folder / key).read_bytes())


AUTOMATED = "Automated"


def rule_preview(lab: Lab, chosen: Sorted) -> dict[str, Any]:
    """The rules each folder would get, written as the app writes them, and what the rule
    engine then does with the downloaded mail: how much each keeps from the AI, how much still
    reaches it and why, and how much it takes from senders left with the AI."""
    assert lab.report is not None
    owner, mentions = lab.report.owner, [lab.report.owner, lab.report.owner_name]
    seen = [sort_rules.Seen.of(parsed) for parsed in lab.mail]
    # Kept folders are plain names at the top of Kept from the AI, as the app makes them.
    entries = [(c.name.strip(), c.senders) for c in chosen.categories]
    entries.append((AUTOMATED, chosen.automated))
    made = {
        name: sort_rules.rules_for(name, senders, seen, mentions, owner)
        for name, senders in entries
    }
    decisions = rules.Engine([rule for found in made.values() for rule in found]).decide(lab.mail)
    found = []
    for name, senders in entries:
        own = set(senders)
        mine = [
            (parsed, decision)
            for parsed, decision in zip(lab.mail, decisions, strict=True)
            if decision.category == name
        ]
        found.append(
            {
                "name": name,
                "rules": [rules.describe_rule(rule) for rule in made[name]],
                # The same rules as parts, for the page to show without sentences.
                "match": [
                    {
                        "kind": "tag" if rule.conditions[0].field == "tag" else "from",
                        "value": rule.conditions[0].value,
                    }
                    for rule in made[name]
                ],
                "kept": sum(not decision.reaches_ai for _, decision in mine),
                "reach": dict(
                    Counter(decision.exception for _, decision in mine if decision.reaches_ai)
                ),
                "others": sum(parsed.from_addr not in own for parsed, _ in mine),
            }
        )
    return {"categories": found, "reach_ai": sum(decision.reaches_ai for decision in decisions)}


def save(lab: Lab, finish: Finish) -> Path:
    """Each sender's side and category beside what the engine chose, so the differences show
    what to fix. With details, also each one's address, score signs and subject patterns."""
    found = lab.found
    engine = {row["sender"]: row for row in found.get("senders", [])}
    chosen = {choice.sender: choice for choice in finish.senders}
    rows = []
    for number, (sender, row) in enumerate(engine.items(), 1):
        choice = chosen.get(sender)
        side = choice.side if choice else row["side"]
        own = (choice.own if choice else row["own"]) and side == "ignores"
        entry: dict[str, Any] = {
            # Without details, a number rather than the sender's address.
            "id": sender if finish.details else f"sender-{number}",
            "count": row["count"],
            "score": row["score"],
            "side": side,
            "engine_side": row["side"],
            "own_category": own,
            "engine_own_category": row["own"],
            "name": ((choice.name.strip() if choice else "") or row["label"]) if own else "",
            "kept": row["kept"],
        }
        if finish.details:
            entry |= {
                "label": row["label"],
                "repeats": row["repeats"],
                "bulk": row["bulk"],
                "one_way": row["one_way"],
                "examples": row["examples"],
            }
        rows.append(entry)
    ignored = [row for row in rows if row["side"] == "ignores"]
    result = {
        "saved": datetime.now(UTC).isoformat(),
        "emails": found.get("total", 0),
        "engine_reached_ai": found.get("reach_ai", 0),
        "calendar": found.get("calendar", 0),
        "senders": len(rows),
        "ignored_senders": len(ignored),
        "categories": [row["name"] for row in ignored if row["own_category"]],
        "moved_by_person": sum(row["side"] != row["engine_side"] for row in rows),
        # What the rule engine would do with them, as the app would write the rules.
        "rules": [
            {**entry, "name": entry["name"] if finish.details else f"category-{number}"}
            | ({} if finish.details else {"rules": len(entry["rules"])})
            for number, entry in enumerate(rule_preview(lab, finish.sorted)["categories"], 1)
        ],
        "rows": rows,
    }
    lab.results.mkdir(parents=True, exist_ok=True)
    path = lab.results / f"sort-lab-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def create_app(lab: Lab, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def check(given: str | None) -> None:
        # Only this run's page may use it, not another site the browser has open.
        if not given or not secrets.compare_digest(given, token):
            raise HTTPException(403, "Open the link the lab printed.")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/setup")
    def setup(x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        server = server_settings()
        # Only whether it's set and the domain to hint at; the page never shows the server.
        return {
            "ready": server is not None,
            "domain": server.domain if server else "",
            "settings_file": str(settings_files()[0]),
        }

    @app.post("/api/start")
    def start(sign_in: SignIn, x_lab_token: str | None = Header(default=None)) -> dict[str, str]:
        check(x_lab_token)
        server = server_settings()
        if server is None:
            raise HTTPException(422, f"No mail server is set. Put {SETTINGS_FILE} beside the lab.")
        with lab.lock:
            if lab.state in {"connecting", "downloading", "grouping"}:
                raise HTTPException(409, "Already running.")
            lab.forget_mail()
            lab.state, lab.error, lab.done, lab.total = "connecting", "", 0, 0
            threading.Thread(target=download, args=(lab, sign_in, server), daemon=True).start()
        return {"state": lab.state}

    @app.get("/api/status")
    def status(x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        return {"state": lab.state, "done": lab.done, "total": lab.total, "error": lab.error}

    @app.get("/api/report")
    def report(x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        if lab.state != "ready":
            raise HTTPException(409, "Not ready yet.")
        return lab.found

    @app.post("/api/rules")
    def preview(body: Sorted, x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        if lab.state != "ready":
            raise HTTPException(409, "Not ready yet.")
        return rule_preview(lab, body)

    @app.post("/api/finish")
    def finish(body: Finish, x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        if lab.state != "ready":
            raise HTTPException(409, "Nothing to finish.")
        path = save(lab, body)
        deleted = lab.forget_mail()
        lab.state = "finished"
        if lab.reveal:
            show_folder(path.parent)
        return {"saved": str(path), "deleted": deleted}

    @app.post("/api/discard")
    def discard(x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        if lab.state in {"connecting", "downloading", "grouping"}:
            raise HTTPException(409, "Wait for the download to stop.")
        deleted = lab.forget_mail()
        lab.state = "idle"
        return {"deleted": deleted}

    return app


def show_folder(folder: Path) -> None:
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)  # noqa: S603, S607


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{secrets.token_hex(4)}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def default_lab() -> Lab:
    """Mail and results go beside the lab, in the folder it was run from, so everything it
    keeps is in one place. Where that folder can't be written, as under Program Files, mail
    goes in the app's data folder and results in Documents."""
    here = _beside_program()
    if _writable(here / RESULTS_FOLDER):
        return Lab(folder=here / MAIL_FOLDER, results=here / RESULTS_FOLDER)
    return Lab(
        folder=app_data_dir() / "sort-lab" / "mail",
        results=Path.home() / "Documents" / "NexusAI Sort Lab",
    )
