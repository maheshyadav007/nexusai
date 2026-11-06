"""The real trigger/runtime path learns batches rather than individual historical messages."""
# ruff: noqa: F401,F811

import json
import re
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from fake_mail import FakeMail, make_mail
from nexusai.api.app import create_app
from nexusai.kernel.config import Config
from nexusai.modules.agent import mail_agent
from nexusai.modules.agent.providers import TextChunk, ToolCall
from test_agent_work import Script, app_config, connect, fake, script, wait


def test_group_learning_uses_one_call_and_a_cached_import_uses_none(
    app_config: Config, script: Script, fake: FakeMail
) -> None:
    calls: list[list[str]] = []

    def stream(request: Any) -> Iterator[Any]:
        script.requests.append(request)
        text = "\n".join(str(message.text) for message in request.messages)
        ids = list(dict.fromkeys(re.findall(r'"id": "([^"]+)"', text)))
        if ids:
            calls.append(ids)
            yield ToolCall(
                "learn",
                "record_triage",
                {
                    "groups": [
                        {
                            "id": key,
                            "importance": "low",
                            "note": "A recurring old report",
                            "uncertain": False,
                        }
                        for key in ids
                    ]
                },
            )
        else:
            yield TextChunk("No new uncertainty.")

    script.stream = stream  # type: ignore[method-assign]
    config = replace(app_config, agent=replace(app_config.agent, learn_emails=400))
    for index in range(10):
        fake.state.deliver(
            make_mail(subject=f"Monthly report {index}", date="Mon, 01 Jan 2024 10:00:00 +0000")
        )
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as client:
        connect(client, fake)
        db = client.app.state.bus.db
        wait(
            lambda: db.fetch_all(
                "SELECT value FROM agent_defaults WHERE key=? AND value='done'",
                (mail_agent.LEARNING_STATE,),
            ),
            "grouped learning to finish",
        )
        assert len(calls) == 1 and len(calls[0]) == 1
        assert not db.fetch_all("SELECT * FROM tasks")
        assert not db.fetch_all("SELECT * FROM reminders")
        assert not db.fetch_all("SELECT * FROM triage_runs")
        assert client.post("/api/queries/mail.organization", json={}).json()["state"] == "done"
        result = client.post("/api/commands/mailAgent.readMore", json={"count": 10})
        assert result.is_success, result.text
        assert len(calls) == 1
        assert not db.fetch_all("SELECT 1 FROM agent_sessions WHERE agent='interview'")


def test_bulk_download_split_into_small_chunks_has_no_per_email_judgements(
    app_config: Config, script: Script, fake: FakeMail
) -> None:
    calls: list[int] = []

    def stream(request: Any) -> Iterator[Any]:
        script.requests.append(request)
        text = "\n".join(str(message.text) for message in request.messages)
        ids = list(dict.fromkeys(re.findall(r'"id": "([^\"]+)"', text)))
        if ids:
            calls.append(len(ids))
            yield ToolCall(
                "learn",
                "record_triage",
                {
                    "groups": [
                        {
                            "id": key,
                            "importance": "low",
                            "note": "A recurring report",
                            "uncertain": False,
                        }
                        for key in ids
                    ]
                },
            )
        else:
            yield TextChunk("Nothing new.")

    script.stream = stream  # type: ignore[method-assign]
    config = replace(
        app_config,
        mail=replace(app_config.mail, backfill_batch=10),
        agent=replace(app_config.agent, learn_emails=400),
    )
    with TestClient(create_app(config), base_url="http://127.0.0.1:4100") as client:
        connect(client, fake)
        with fake.state.lock:
            for index in range(60):
                fake.state.deliver(
                    make_mail(
                        subject=f"Recurring report {index}", date="Mon, 01 Jan 2024 10:00:00 +0000"
                    )
                )
        db = client.app.state.bus.db
        wait(
            lambda: db.fetch_all("SELECT COUNT(*) n FROM mail_learning_members")[0]["n"] == 60,
            "all chunks to enter grouped learning",
        )
        wait(
            lambda: db.fetch_all(
                "SELECT value FROM agent_defaults WHERE key=? AND value='done'",
                (mail_agent.LEARNING_STATE,),
            ),
            "group learning to finish",
        )
        assert calls == [1]
        assert not db.fetch_all("SELECT 1 FROM triage_runs")
        assert not db.fetch_all("SELECT 1 FROM tasks")
