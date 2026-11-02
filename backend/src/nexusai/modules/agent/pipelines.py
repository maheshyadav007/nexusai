"""Work that runs on a timer with no agent or model, such as keeping mail in step with the server.

Anything added to PIPELINES shows on the Schedules page and in the Cockpit, with Stop and Run now.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from nexusai.contracts.agent import Pipeline, PipelineFact
from nexusai.contracts.mail import GetMailStatus, MailStatus
from nexusai.kernel.module import CommandError, Context
from nexusai.modules.mail import module as mail

SECONDS_IN_MINUTE = 60
MAIL_STATES: dict[str, Any] = {
    "live": "waiting",
    "paused": "stopped",
    "off": "stopped",
    "failed": "problem",
    "offline": "problem",
}
MAIL_MESSAGES = {
    "paused": "Stopped. Nothing is downloaded, and changes made here wait, until you resume.",
    "off": "Connect a mail account to start.",
    "syncing": "Downloading mail.",
    "backfilling": "Downloading older mail.",
    "connecting": "Connecting to the server.",
}


def _every(seconds: int) -> str:
    if seconds == SECONDS_IN_MINUTE:
        return "Every minute"
    if seconds % SECONDS_IN_MINUTE:
        return f"Every {seconds} seconds"
    return f"Every {seconds // SECONDS_IN_MINUTE} minutes"


def _mail_view(ctx: Context) -> Pipeline:
    status = cast(MailStatus, mail.get_status(GetMailStatus(), ctx))
    facts = [
        PipelineFact(label="On the server", value=f"{status.server_total:,}"),
        PipelineFact(label="On this computer", value=f"{status.pulled:,}"),
        PipelineFact(
            label="Download limit",
            value=f"Newest {status.pull_limit:,}" if status.pull_limit else "All of it",
        ),
    ]
    if status.last_found_at:
        words = f"Found {status.last_found:,}, pulled {status.last_pulled:,}"
        facts.append(PipelineFact(label="Last new mail", value=words))
    return Pipeline(
        id="mail-sync",
        title="Mail sync",
        cadence=f"{_every(status.check_every_seconds)}, and when the server announces new mail",
        state=MAIL_STATES.get(status.state, "running"),
        message=status.message or MAIL_MESSAGES.get(status.state),
        facts=facts if status.account else [],
        last_run=status.last_check,
        next_run=status.next_check,
        available=status.account is not None,
        link="/connectors",
    )


@dataclass(frozen=True)
class Entry:
    view: Callable[[Context], Pipeline]
    pause: Callable[[Context, bool], None]
    run: Callable[[Context], None]


PIPELINES = {
    "mail-sync": Entry(_mail_view, mail.pause_sync, lambda ctx: mail.check_now()),
}


def entry(identifier: str) -> Entry:
    found = PIPELINES.get(identifier)
    if found is None:
        raise CommandError("pipelines.not_found", "There's no such schedule.", 404)
    return found


def views(ctx: Context) -> list[Pipeline]:
    return [item.view(ctx) for item in PIPELINES.values()]
