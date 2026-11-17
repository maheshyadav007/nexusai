# ruff: noqa: F401,F811
"""Group learning must survive the data guard and imperfect model output.

Regression: group ids were 64-character SHA-256 hashes. About 3% of them hold a run of ten
digits that the Indian phone rule masked, so the model saw `...84bf<PHONE_7>a329...`, copied it
back imperfectly, and the whole batch was discarded on every retry until learning failed and the
first meeting never started.
"""

import hashlib
import json
import random
import re

import pytest

from nexusai.kernel.module import Context
from nexusai.modules.agent import bulk_learning, guard
from nexusai.modules.agent.guard import DataGuard
from test_mail_organization import add, ctx  # noqa: F401

LEGACY_INDIAN = r"(?<![\d+])(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"
LEGACY_INTL = r"(?<![\d+])\+\d{1,3}[\s-]?\(?\d{1,4}\)?(?:[\s-]?\d{2,4}){2,4}(?!\d)"
# A real group id from the failing run's shape: "9173258138" inside it looks like a phone number.
PHONE_SHAPED_HASH = "44d168068cd5ac4d84bf9173258138a329c524d9f44a828171311584f0a9ac66"


def legacy_rules() -> guard.GuardRules:
    rules = guard.default_rules()
    patterns = {"Indian phone numbers": LEGACY_INDIAN, "International phone numbers": LEGACY_INTL}
    return rules.model_copy(
        update={
            "rules": [
                rule.model_copy(update={"pattern": patterns.get(rule.name, rule.pattern)})
                for rule in rules.rules
            ]
        }
    )


def phone_shaped_sender() -> str:
    """A sender whose group id the legacy rule would have masked."""
    legacy = re.compile(LEGACY_INDIAN)
    for index in range(10_000):
        sender = f"sender{index}@example.com"
        if legacy.search(bulk_learning.group_id("test", sender, "Monthly report")):
            return sender
    raise AssertionError("no phone-shaped id found")


def run_for(ctx: Context, batch: int) -> dict[str, object]:
    row = ctx.bus.db.fetch_all(
        "SELECT * FROM trigger_runs WHERE event=?", (f"{bulk_learning.PREFIX}{batch}",)
    )[0]
    return dict(row)


# The guard itself


def test_phone_rules_never_mask_inside_hashes_or_codes(ctx: Context) -> None:
    masking = DataGuard(ctx.bus.db, guard.default_rules())
    assert masking.mask(PHONE_SHAPED_HASH) == PHONE_SHAPED_HASH
    random.seed(7)
    for _ in range(3000):
        value = hashlib.sha256(str(random.random()).encode()).hexdigest()
        assert masking.mask(value) == value
        assert masking.mask(value[:32]) == value[:32]
    for code in ("Order AB9876543210", "ref_9876543210", "tracking 9876543210X"):
        assert masking.mask(code) == code


@pytest.mark.parametrize(
    "text",
    [
        "Call 9876543210 today",
        "Phone: +91 98765 43210.",
        "+91-98765-43210",
        "(9876543210)",
        "Reach me on +1 415 555 0100",
    ],
)
def test_phone_rules_still_mask_real_numbers(ctx: Context, text: str) -> None:
    masked = DataGuard(ctx.bus.db, guard.default_rules()).mask(text)
    assert "<PHONE_" in masked
    assert not re.search(r"\d{5}", masked.replace("<PHONE_", "<"))


def test_saved_legacy_rules_are_upgraded_and_edited_rules_kept(ctx: Context) -> None:
    home = ctx.config.home
    legacy = legacy_rules()
    custom = legacy.rules[0].model_copy(
        update={"name": "Mine", "kind": "PHONE", "pattern": r"(?<!\d)\d{10}(?!\d)"}
    )
    guard.save_rules(home, legacy.model_copy(update={"rules": [*legacy.rules, custom]}))
    loaded = guard.load_rules(home)
    patterns = {rule.name: rule.pattern for rule in loaded.rules}
    assert patterns["Indian phone numbers"] == guard.UPGRADED_PATTERNS[LEGACY_INDIAN]
    assert patterns["International phone numbers"] == guard.UPGRADED_PATTERNS[LEGACY_INTL]
    assert patterns["Mine"] == r"(?<!\d)\d{10}(?!\d)"
    # Written back, so the next load has nothing to upgrade.
    saved = json.loads((home / "system" / guard.FILE_NAME).read_text())
    assert LEGACY_INDIAN not in {rule["pattern"] for rule in saved["rules"]}
    assert {rule.pattern for rule in guard.default_rules().rules}.isdisjoint(
        guard.UPGRADED_PATTERNS
    )


# Group learning through the guard


@pytest.mark.parametrize("rules", ["current", "legacy"])
def test_phone_shaped_group_id_learns_through_the_guard(ctx: Context, rules: str) -> None:
    """End to end: masked prompt, model copies ids, arguments restored, batch saved."""
    sender = phone_shaped_sender()
    add(ctx, "Monthly report", sender=sender, days=10)
    for index in range(29):
        add(ctx, "Monthly report", sender=f"other{index}@example.com", days=10)
    assert bulk_learning.queue(ctx) == 30
    batch = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")[0]
    request, _ = bulk_learning.batch_request(ctx, run_for(ctx, batch["id"]), {})
    # No hash reaches the model, so nothing in an id can look like anything.
    assert not re.search(r"[0-9a-f]{64}", request.task)
    masking = DataGuard(ctx.bus.db, guard.default_rules() if rules == "current" else legacy_rules())
    seen = masking.mask(request.task)
    ids = re.findall(r'"id": "([^"]+)"', seen)
    assert ids == [f"g{index}" for index in range(1, 31)]
    arguments = masking.restore_arguments(
        {"groups": [{"id": key, "importance": "low", "note": "Report"} for key in ids]}
    )
    result = bulk_learning.record(ctx, batch["id"], arguments, 1)
    assert result.startswith("Learned 30")
    assert ctx.bus.db.fetch_all("SELECT status FROM mail_learning_batches")[0]["status"] == "done"


def test_partial_results_are_kept_and_only_missing_groups_are_asked_again(ctx: Context) -> None:
    for index in range(30):
        add(ctx, "Monthly report", sender=f"person{index}@example.com", days=10)
    bulk_learning.queue(ctx)
    batch = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")[0]
    groups = [{"id": f"g{index}", "importance": "low", "note": "Report"} for index in range(1, 21)]
    groups[4]["importance"] = "urgent"  # g5: invalid, dropped alone
    groups.append({"id": "g1<phone>", "importance": "low"})  # mangled: reported, not fatal
    groups.append({"id": "G21", "importance": "HIGH", "note": "Case and spacing are fine"})
    first = bulk_learning.record(ctx, batch["id"], {"groups": groups}, 1)
    assert first.startswith("Saved 20 groups. Still missing: g5, g22,")
    assert "g5 has invalid fields" in first and "unknown id" in first
    learned = ctx.bus.db.fetch_all("SELECT COUNT(*) n FROM mail_learning_groups WHERE learned=1")
    assert learned[0]["n"] == 20
    assert ctx.bus.db.fetch_all("SELECT status FROM mail_learning_batches")[0]["status"] != "done"

    # The model's own retry, or the next run, sees only what is missing, under the same names.
    request, _ = bulk_learning.batch_request(ctx, run_for(ctx, batch["id"]), {})
    remaining = re.findall(r'"id": "([^"]+)"', request.task)
    assert remaining == ["g5", *[f"g{index}" for index in range(22, 31)]]
    second = bulk_learning.record(
        ctx,
        batch["id"],
        {"groups": [{"id": key, "importance": "normal", "note": "Report"} for key in remaining]},
        2,
    )
    assert second.startswith("Learned 10")
    assert ctx.bus.db.fetch_all("SELECT status FROM mail_learning_batches")[0]["status"] == "done"
    assert (
        ctx.bus.db.fetch_all(
            "SELECT importance FROM mail_learning_groups WHERE learned=1 AND note='Case and spacing are fine'"
        )[0]["importance"]
        == "high"
    )


def test_real_ids_are_still_accepted(ctx: Context) -> None:
    add(ctx, "Payslip", days=10)
    bulk_learning.queue(ctx)
    batch = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")[0]
    key = json.loads(batch["groups_json"])[0]
    result = bulk_learning.record(
        ctx, batch["id"], {"groups": [{"id": key, "importance": "low"}]}, 1
    )
    assert result.startswith("Learned 1")


def test_partial_progress_survives_a_failed_turn(ctx: Context) -> None:
    for index in range(3):
        add(ctx, "Monthly report", sender=f"person{index}@example.com", days=10)
    bulk_learning.queue(ctx)
    batch = ctx.bus.db.fetch_all("SELECT * FROM mail_learning_batches")[0]
    bulk_learning.record(ctx, batch["id"], {"groups": [{"id": "g2", "importance": "low"}]}, 1)
    run = run_for(ctx, batch["id"])
    bulk_learning.after_turn(ctx, run, 1, "Stopped at its limit of 30000 tokens.")
    assert run_for(ctx, batch["id"])["status"] == "pending"
    learned = ctx.bus.db.fetch_all("SELECT COUNT(*) n FROM mail_learning_groups WHERE learned=1")
    assert learned[0]["n"] == 1


def test_a_batch_gets_a_budget_for_a_retry() -> None:
    task = "x" * 60_000  # about thirty groups with samples
    # The default per-email triage limit is 30,000; one batch alone is ~35,000 per call.
    assert bulk_learning.token_budget(task) >= 3 * (len(task) // 3)
    assert bulk_learning.token_budget(task) > 30_000 * 2


# The interview's answers


def test_interview_uses_short_ids_and_maps_answers_back(ctx: Context) -> None:
    groups = [
        {"id": PHONE_SHAPED_HASH, "sender": "a@example.com"},
        {"id": "b" * 64, "sender": "b@example.com"},
    ]
    shown = bulk_learning.alias_interview_groups(ctx, "interview-1", groups)
    assert [group["id"] for group in shown] == ["q1", "q2"]
    resolved, unknown = bulk_learning.interview_answers(
        ctx, "interview-1", {"q1": "High", " Q2 ": "low", "q9": "low"}
    )
    assert resolved == {PHONE_SHAPED_HASH: "high", "b" * 64: "low"}
    assert unknown == ["q9"]
    # Another interview's names don't leak in, and an older interview's real ids still work.
    legacy, none = bulk_learning.interview_answers(ctx, "older", {PHONE_SHAPED_HASH: "low"})
    assert legacy == {PHONE_SHAPED_HASH: "low"} and none == []


# Posty is the one name the person meets


@pytest.mark.parametrize("agent", ["session", "mail", "interview"])
def test_every_agent_knows_it_is_posty_and_nexusai_is_the_app(ctx: Context, agent: str) -> None:
    from nexusai.modules.agent import prompts_builder

    layers = prompts_builder.build_layers(ctx.config, agent, db=ctx.bus.db)
    text = "\n".join(layer.text for layer in layers)
    system = layers[0].text
    assert "You are NexusAI" not in text
    assert "Posty, their chief of staff in NexusAI" in system
    if agent == "session":
        assert "You are Posty (@posty). Your chief of staff." in text
    else:
        assert "on Posty's team" in system


# The same suggestion isn't asked twice


def test_reworded_tasks_and_memory_are_not_suggested_twice(ctx: Context) -> None:
    from nexusai.modules.agent import memory
    from nexusai.modules.planner import module as planner

    planner.add_task(ctx, "Reply to Priya about the budget", None, 7, "agent", True)
    assert planner.has_task(ctx.bus.db, "Respond to Priya re budget", 7)
    assert not planner.has_task(ctx.bus.db, "Respond to Priya re budget", 8)
    assert not planner.has_task(ctx.bus.db, "Book the Pune hotel", 7)

    db, home = ctx.bus.db, ctx.config.home
    memory.propose(db, "Mail agent", "Meera Iyer is my manager.", "/mail/thread/1", home)
    memory.propose(db, "Mail agent", "meera iyer is MY manager", "/mail/thread/2", home)
    assert [row.text for row in memory.proposals(db)] == ["Meera Iyer is my manager."]
    proposal = memory.proposals(db)[0].id
    memory.decide_proposal(db, home, proposal, False)
    memory.propose(db, "Mail agent", "Meera Iyer is my manager", "/mail/thread/3", home)
    assert memory.proposals(db) == []  # turned down, so not asked again
    memory.remember(home, db, "Posty", ["Prefers short replies."], False, None)
    memory.propose(db, "Mail agent", "prefers short replies", "/mail/thread/4", home)
    assert memory.proposals(db) == []  # already known
    memory.propose(db, "Mail agent", "Works on the RRC launch.", "/mail/thread/5", home)
    assert len(memory.proposals(db)) == 1
