from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nexusai.api.app import create_app
from nexusai.kernel.config import Config


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config), base_url="http://127.0.0.1:8765") as test_client:
        yield test_client


def test_setup_resumes_where_it_stopped_and_finishes(client: TestClient) -> None:
    assert client.post("/api/queries/onboarding.state").json() == {
        "completed": False,
        "current_step": None,
        "checklist_dismissed": False,
    }
    client.post("/api/commands/onboarding.setStep", json={"step": "profile"})
    assert client.post("/api/queries/onboarding.state").json()["current_step"] == "profile"
    done = client.post("/api/commands/onboarding.finish").json()
    assert done == {"completed": True, "current_step": None, "checklist_dismissed": False}


def test_profile_saves_and_its_event_names_only_the_fields(client: TestClient) -> None:
    empty = client.post("/api/queries/profile.get").json()
    assert empty["name"] == "" and empty["tone"] == "friendly"
    profile = {**empty, "name": "Asha", "about": "Runs the supplier programme"}
    assert client.post("/api/commands/profile.update", json=profile).json()["name"] == "Asha"
    assert client.post("/api/queries/profile.get").json()["about"] == profile["about"]
    events = client.post("/api/events/log", json={}).json()["events"]
    assert events[-1]["payload"] == {"fields": ["name", "about"]}
    assert "supplier" not in str(events)
    client.post("/api/commands/profile.update", json=profile)
    assert len(client.post("/api/events/log", json={}).json()["events"]) == len(events)


def test_the_checklist_stays_hidden_once_dismissed(client: TestClient) -> None:
    assert client.post("/api/queries/onboarding.state").json()["checklist_dismissed"] is False
    client.post("/api/commands/onboarding.finish", json={})
    state = client.post("/api/commands/onboarding.dismissChecklist", json={}).json()
    assert state["checklist_dismissed"] is True and state["completed"] is True
    assert client.post("/api/queries/onboarding.state").json()["checklist_dismissed"] is True


def test_a_starter_set_can_be_told_from_the_persons_own_words(client: TestClient) -> None:
    client.post("/api/commands/prompts.useStarters", json={})
    prompts = client.post("/api/queries/prompts.list").json()["prompts"]
    importance = next(p for p in prompts if p["name"] == "importance")
    assert importance["content"] == importance["starter"]
    client.post(
        "/api/commands/prompts.save",
        json={"kind": "personal", "name": "importance", "content": "Mine"},
    )
    prompts = client.post("/api/queries/prompts.list").json()["prompts"]
    importance = next(p for p in prompts if p["name"] == "importance")
    assert importance["content"] != importance["starter"]
