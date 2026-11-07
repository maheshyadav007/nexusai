"""What every eval run shares: a throwaway Home, the account's models, and the plan's usage.

The Home is new and empty each time, so no real mail or memory is read, and the person's own Home
is never opened. The ChatGPT sign-in is the person's own, from the Keychain, because evals are
meant to measure the real model: only run them when the person has agreed to the spend.
"""

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from nexusai.api.app import MODULES
from nexusai.contracts.models import ListModels
from nexusai.kernel.config import Config, load_config
from nexusai.kernel.database import Database
from nexusai.kernel.event_bus import MIGRATIONS as BUS_MIGRATIONS
from nexusai.kernel.event_bus import EventBus
from nexusai.kernel.home import create_home
from nexusai.kernel.module import Context
from nexusai.modules.agent import gateway
from nexusai.modules.agent.providers import ChatGptProvider
from nexusai.modules.models import chatgpt
from nexusai.modules.models import module as models

# The efforts evals may use. Never above high, and high only for the judge.
EFFORTS = {"light": "low", "medium": "medium", "high": "high"}


@contextmanager
def scratch_home() -> Iterator[tuple[Context, Path]]:
    with tempfile.TemporaryDirectory(prefix="nexusai-eval-") as folder:
        home = Path(folder) / "home"
        create_home(home)
        config: Config = load_config(home)
        db = Database(home / "system" / "nexusai.db")
        db.migrate([*BUS_MIGRATIONS, *(m for module in MODULES for m in module.migrations)])
        ctx = Context(bus=EventBus(db, config), config=config, trace_id="eval")
        yield ctx, home


def account_models(ctx: Context) -> list[tuple[str, str]]:
    """(id, name) for each model the person's ChatGPT account offers."""
    listed = models.list_models(ListModels(), ctx)
    return [(item.id, item.name) for item in listed.models]


def _key(name: str) -> str:
    """ "GPT-5.6 Sol", "gpt-5.6-sol" and "5.6 Sol" all become "5.6 sol"."""
    words = re.sub(r"[^a-z0-9.]+", " ", name.casefold()).split()
    return " ".join(word for word in words if word != "gpt")


def resolve(ctx: Context, wanted: str) -> tuple[str, str]:
    """A picker name such as "6.1 Sol" to the account's (id, name). Refuses what isn't offered."""
    target = _key(wanted)
    offered = account_models(ctx)
    for identifier, name in offered:
        if target in {_key(name), _key(identifier)}:
            return identifier, name
    names = ", ".join(name for _, name in offered)
    raise SystemExit(f"Your account doesn't offer {wanted}. It offers: {names}")


def use_model(identifier: str, effort: str | None) -> None:
    """Every call in this process goes to this model at this effort."""
    gateway.resolve_provider = lambda ctx: (ChatGptProvider(ctx), identifier)
    gateway.EFFORT_OVERRIDE = EFFORTS[effort] if effort else None


def plan_usage() -> dict[str, float]:
    """The plan's usage figures ChatGPT sent with its last reply, as numbers where they are."""
    found: dict[str, float] = {}
    for name, value in chatgpt.PLAN_USAGE.items():
        try:
            found[name] = float(value)
        except ValueError:
            continue
    return found


def used_percent(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """How many points of each window a run used, from the headers that report a percent."""
    return {
        name: round(after[name] - before.get(name, after[name]), 2)
        for name in after
        if "percent" in name
    }


def tokens_since(ctx: Context, first_call: int) -> dict[str, int]:
    row = ctx.bus.db.fetch_all(
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS input,"
        " COALESCE(SUM(output_tokens), 0) AS output FROM model_calls WHERE id > ?",
        (first_call,),
    )[0]
    return {"calls": int(row["calls"]), "input": int(row["input"]), "output": int(row["output"])}


def last_call(ctx: Context) -> int:
    return int(ctx.bus.db.fetch_all("SELECT COALESCE(MAX(id), 0) AS n FROM model_calls")[0]["n"])


def describe(value: Any) -> str:
    return (
        ", ".join(f"{k}={v}" for k, v in value.items()) if isinstance(value, dict) else str(value)
    )
