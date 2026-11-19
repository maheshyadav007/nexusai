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
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from nexusai.contracts.mail import MailAuth, MailProfile, ServerSettings
from nexusai.kernel.home import app_data_dir
from nexusai.modules.mail import grouping
from nexusai.modules.mail.imap import Fetched, Folder, ImapSession, SignInFailed, synced_folders
from nexusai.modules.mail.parse import parse_message
from nexusai.modules.mail.pop3 import Pop3Session

BATCH = 50
SKIPPED_ROLES = {"trash", "junk", "drafts"}
SAMPLES = 10
MISSED_SENDERS = 40
PAGE = Path(__file__).with_name("page.html")


class Session(Protocol):
    def folders(self) -> list[Folder]: ...
    def select(self, name: str) -> tuple[int, int]: ...
    def all_uids(self) -> list[int]: ...
    def fetch(self, uids: list[int]) -> list[Fetched]: ...
    def close(self) -> None: ...


class SignIn(BaseModel):
    address: str = Field(min_length=3, max_length=320)
    user: str = Field(default="", max_length=320)
    password: str = Field(min_length=1, max_length=1000)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["imap", "pop3"] = "imap"
    secure: bool = True
    verify_cert: bool = True
    limit: int = Field(default=15000, ge=1, le=100000)


class GroupFeedback(BaseModel):
    id: str
    name: str = Field(default="", max_length=200)
    section: str = Field(default="", max_length=40)
    smart: bool | None = None
    verdict: Literal["", "right", "wrong", "unsure"] = ""
    note: str = Field(default="", max_length=2000)
    not_belonging: list[str] = Field(default_factory=list)


class MissFeedback(BaseModel):
    sender: str = Field(max_length=320)
    verdict: Literal["", "tool", "right", "unsure"] = ""
    note: str = Field(default="", max_length=2000)


class Finish(BaseModel):
    groups: list[GroupFeedback] = Field(default_factory=list)
    misses: list[MissFeedback] = Field(default_factory=list)
    details: bool = True


@dataclass
class Lab:
    folder: Path
    results: Path
    state: str = "idle"
    done: int = 0
    total: int = 0
    error: str = ""
    report: grouping.Report | None = None
    found: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def forget_mail(self) -> int:
        """Deletes every downloaded email. Returns how many there were."""
        count = len(list(self.folder.glob("*.eml"))) if self.folder.exists() else 0
        shutil.rmtree(self.folder, ignore_errors=True)
        self.report, self.found = None, {}
        return count


def company_defaults() -> dict[str, Any]:
    """The company server, from the settings files the app reads, for the form to start with."""
    candidates = [os.environ.get("NEXUSAI_ENV_FILE", "")]
    base = app_data_dir().parent
    candidates += [str(base / name / "company.env") for name in ("NexusAI", "NexusAI Pilot")]
    candidates.append(str(Path(__file__).resolve().parents[3] / ".env"))
    values: dict[str, str] = {}
    for candidate in candidates:
        path = Path(candidate) if candidate else None
        if path is None or not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, equals, value = line.strip().removeprefix("export ").partition("=")
            if equals and key.strip().startswith("NEXUSAI_MAIL_"):
                values.setdefault(key.strip(), value.strip().strip("\"'"))
    on = {"1", "true", "yes", "on"}
    protocol = values.get("NEXUSAI_MAIL_PROTOCOL", "imap").lower()
    return {
        "host": values.get("NEXUSAI_MAIL_HOST", ""),
        "port": int(values.get("NEXUSAI_MAIL_PORT", "995" if protocol == "pop3" else "993")),
        "protocol": protocol if protocol in {"imap", "pop3"} else "imap",
        "secure": values.get("NEXUSAI_MAIL_SECURE", "true").lower() in on,
        "verify_cert": values.get("NEXUSAI_MAIL_VERIFY_CERT", "true").lower() in on,
        "domain": values.get("NEXUSAI_MAIL_DOMAIN", ""),
    }


def open_session(sign_in: SignIn) -> Session:
    profile = MailProfile(
        label="Sort lab",
        protocol=sign_in.protocol,
        imap=ServerSettings(
            host=sign_in.host,
            port=sign_in.port,
            secure=sign_in.secure,
            verify_cert=sign_in.verify_cert,
        ),
        smtp=ServerSettings(host=sign_in.host, port=465),
        auth=MailAuth(user=sign_in.user or sign_in.address),
        address=sign_in.address,
    )
    if sign_in.protocol == "pop3":
        numbers: dict[str, int] = {}

        def uids(names: list[str]) -> dict[str, int]:
            for name in names:
                numbers.setdefault(name, len(numbers) + 1)
            return dict(numbers)

        return Pop3Session(profile, sign_in.password, 60, never_delete=True, uids=uids)
    return ImapSession(profile, sign_in.password, 60, never_delete=True)


def download(lab: Lab, sign_in: SignIn) -> None:
    """Newest mail first, from every folder but trash, junk and drafts, up to the limit."""
    session: Session | None = None
    try:
        lab.state = "connecting"
        session = open_session(sign_in)
        plan: list[tuple[str, list[int]]] = []
        wanted = sign_in.limit
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
        lab.report = grouping.group_mailbox(grouping.read_folder(lab.folder))
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


def _summary(path: Path) -> dict[str, str]:
    parsed = parse_message(path.read_bytes())
    return {"key": path.name, "subject": parsed.subject, "sender": parsed.from_addr}


def describe(lab: Lab) -> dict[str, Any]:
    """What the page shows: every group with sample emails, and the biggest senders left smart."""
    report = lab.report
    assert report is not None
    groups = []
    for group in report.groups:
        data = json.loads(grouping.to_json(grouping.Report("", "", [group], {})))["groups"][0]
        data["emails"] = [_summary(lab.folder / key) for key in group.members[:SAMPLES]]
        groups.append(data)
    loose = [key for key, decision in report.decisions.items() if decision.group is None]
    by_sender: dict[str, list[dict[str, str]]] = {}
    for key in loose:
        summary = _summary(lab.folder / key)
        by_sender.setdefault(summary["sender"], []).append(summary)
    missed = sorted(by_sender.items(), key=lambda item: -len(item[1]))[:MISSED_SENDERS]
    reach = sum(decision.reaches_ai for decision in report.decisions.values())
    return {
        "owner": report.owner,
        "owner_name": report.owner_name,
        "total": len(report.decisions),
        "reach_ai": reach,
        "ungrouped": len(loose),
        "groups": groups,
        "missed": [
            {"sender": sender, "count": len(items), "emails": items[:SAMPLES]}
            for sender, items in missed
        ],
    }


def save(lab: Lab, finish: Finish) -> Path:
    """The names and feedback, and with details, each group's senders and subject patterns."""
    found = lab.found
    engine = {group["id"]: group for group in found.get("groups", [])}
    groups = []
    for number, item in enumerate(finish.groups, 1):
        group = engine.get(item.id, {})
        row: dict[str, Any] = {
            # The engine's id holds a sender's address, so without details it's just a number.
            "id": item.id if finish.details else f"group-{number}",
            "engine_name": group.get("label", ""),
            "name": item.name or group.get("label", ""),
            "engine_section": group.get("section", ""),
            "section": item.section or group.get("section", ""),
            "smart": group.get("smart") if item.smart is None else item.smart,
            "count": group.get("count", 0),
            "verdict": item.verdict,
            "note": item.note,
            "not_belonging": len(item.not_belonging),
        }
        if finish.details:
            row |= {
                "senders": group.get("senders", []),
                "patterns": group.get("patterns", []),
                "reasons": group.get("reasons", []),
                "mentions": group.get("mentions", 0),
                "not_belonging_subjects": [
                    email["subject"]
                    for email in group.get("emails", [])
                    if email["key"] in set(item.not_belonging)
                ],
            }
        groups.append(row)
    misses = [
        {"verdict": miss.verdict, "note": miss.note, "count": _missed_count(found, miss.sender)}
        | ({"sender": miss.sender} if finish.details else {})
        for miss in finish.misses
        if miss.verdict or miss.note
    ]
    sections: Counter[str] = Counter()
    for group in found.get("groups", []):
        sections[group["section"]] += group["count"]
    result = {
        "saved": datetime.now(UTC).isoformat(),
        "emails": found.get("total", 0),
        "reached_ai": found.get("reach_ai", 0),
        "ungrouped": found.get("ungrouped", 0),
        "engine_sections": dict(sections),
        "groups": groups,
        "missed_senders": misses,
    }
    lab.results.mkdir(parents=True, exist_ok=True)
    path = lab.results / f"sort-lab-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def _missed_count(found: dict[str, Any], sender: str) -> int:
    return next((m["count"] for m in found.get("missed", []) if m["sender"] == sender), 0)


def create_app(lab: Lab, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def check(given: str | None) -> None:
        # Only this run's page may use it, not another site the browser has open.
        if not given or not secrets.compare_digest(given, token):
            raise HTTPException(403, "Open the link the lab printed.")

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/defaults")
    def defaults(x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        return company_defaults()

    @app.post("/api/start")
    def start(sign_in: SignIn, x_lab_token: str | None = Header(default=None)) -> dict[str, str]:
        check(x_lab_token)
        with lab.lock:
            if lab.state in {"connecting", "downloading", "grouping"}:
                raise HTTPException(409, "Already running.")
            lab.forget_mail()
            lab.state, lab.error, lab.done, lab.total = "connecting", "", 0, 0
            threading.Thread(target=download, args=(lab, sign_in), daemon=True).start()
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

    @app.post("/api/finish")
    def finish(body: Finish, x_lab_token: str | None = Header(default=None)) -> dict[str, Any]:
        check(x_lab_token)
        if lab.state != "ready":
            raise HTTPException(409, "Nothing to finish.")
        path = save(lab, body)
        deleted = lab.forget_mail()
        lab.state = "finished"
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


def default_lab() -> Lab:
    base = app_data_dir() / "sort-lab"
    return Lab(folder=base / "mail", results=base / "results")
