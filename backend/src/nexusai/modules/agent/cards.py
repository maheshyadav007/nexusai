"""Who each agent is. Names, handles and mascots live in the agent files (`plugins.py`) and the
person's renames, and nowhere else, so changing a name is a change in one place."""

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cache
from typing import Any

from nexusai.contracts.agent import HANDLE_PATTERN, AgentCard, AgentMascot
from nexusai.kernel.database import Database, Migration
from nexusai.kernel.module import CommandError
from nexusai.modules.agent import plugins

MIGRATION = Migration(
    "agent_cards_001",
    """
CREATE TABLE agent_card_overrides (
  id TEXT PRIMARY KEY, name TEXT, handle TEXT, mascot_seed TEXT, updated TEXT NOT NULL);
""",
)
# Chats of the person's own schedules and triggers belong to those agents, not the template.
YOURS_MIGRATION = Migration(
    "agent_cards_yours_001",
    """
UPDATE agent_sessions SET agent = 'schedule-' || (
  SELECT id FROM schedules WHERE last_session = agent_sessions.id AND kind = 'prompt')
  WHERE id IN (SELECT last_session FROM schedules WHERE kind = 'prompt');
UPDATE agent_sessions SET agent = 'trigger-' || (
  SELECT id FROM agent_triggers WHERE session = agent_sessions.id AND kind = 'custom')
  WHERE id IN (SELECT session FROM agent_triggers WHERE kind = 'custom');
""",
)
PERSON = "person"
HANDLE = re.compile(HANDLE_PATTERN)
# An @handle at the very start of a message: "@mail why is this in Finance?"
ADDRESSED = re.compile(r"^\s*@([a-z][a-z0-9-]{1,23})\b[\s,:]*", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\{\{\s*(self|agent\.([a-z0-9-]+))\.(name|handle)\s*\}\}")


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    handle: str
    role: str
    can_do: tuple[str, ...]
    default: bool
    may_assign_to: tuple[str, ...]
    talks_to_person: bool
    accepts: tuple[str, ...]
    mascot_style: str
    mascot_seed: str
    version: str
    renamed: bool = False
    # "yours" for an agent the person made. Its name is its schedule's or trigger's title.
    kind: str = "built_in"
    # Whose prompt and tools it runs with. Built-in agents are their own engine.
    engine: str = ""
    instructions: str = ""
    # A template for the person's own agents, not a member of the team.
    hidden: bool = False
    # It reads mail from anyone, so it may never send, delete or change settings.
    untrusted_mail: bool = False

    @property
    def at(self) -> str:
        return f"@{self.handle}"


@cache
def _files() -> dict[str, Card]:
    found: dict[str, Card] = {}
    # Sorted by file name, as the card folder was, so the team is listed in the same order.
    for file in sorted(plugins.agent_files().values(), key=lambda item: item.name):
        raw: dict[str, Any] = file.ours
        mascot = raw.get("mascot", {}) if isinstance(raw.get("mascot"), dict) else {}
        for key in ("displayName", "handle", "role"):
            if not str(raw.get(key, "")).strip():
                raise ValueError(f"Agent {file.name} needs nexusai.{key}")
        card = Card(
            id=file.name,
            name=str(raw["displayName"]),
            handle=str(raw["handle"]),
            role=str(raw["role"]),
            can_do=tuple(str(item) for item in raw.get("canDo", ())),
            default=bool(raw.get("lead", False)),
            may_assign_to=tuple(str(item) for item in raw.get("mayAssignTo", ())),
            talks_to_person=bool(raw.get("talksToPerson", False)),
            accepts=tuple(str(item) for item in raw.get("accepts", ())),
            mascot_style=str(mascot.get("style", "round")),
            mascot_seed=str(mascot.get("seed", file.name)),
            version=file.hash,
            engine=file.name,
            hidden=bool(raw.get("hidden", False)),
            untrusted_mail=bool(raw.get("readsUntrustedMail", False)),
        )
        if not HANDLE.match(card.handle):
            raise ValueError(f"Card {card.id} has a handle that isn't allowed: {card.handle}")
        found[card.id] = card
    defaults = [card.id for card in found.values() if card.default]
    if len(defaults) != 1:
        raise ValueError(f"Exactly one card must be the default, found {defaults or 'none'}")
    handles = [card.handle for card in found.values()]
    if len(set(handles)) != len(handles):
        raise ValueError("Two cards share a handle")
    return found


def all_cards(db: Database, *, include_hidden: bool = False) -> dict[str, Card]:
    """Every card: the files, the agents the person made, and the person's renames on top."""
    cards = {card.id: card for card in _files().values() if include_hidden or not card.hidden}
    yours = _yours(db, {card.handle for card in _files().values()})
    cards.update(yours)
    lead = next(card for card in cards.values() if card.default)
    # The lead may give work to any agent the person made, as well as those in its file.
    cards[lead.id] = replace(lead, may_assign_to=(*lead.may_assign_to, *yours))
    for row in db.fetch_all("SELECT * FROM agent_card_overrides"):
        card = cards.get(row["id"])
        if card is None:
            continue
        cards[card.id] = replace(
            card,
            # A person's agent is named by its title, so only its handle and face are overridden.
            name=(row["name"] if card.kind == "built_in" else None) or card.name,
            handle=row["handle"] or card.handle,
            mascot_seed=row["mascot_seed"] or card.mascot_seed,
            renamed=bool(row["name"] or row["handle"]),
        )
    return cards


YOURS = (
    ("schedule", "SELECT id, title, prompt, created FROM schedules WHERE kind = 'prompt'"),
    ("trigger", "SELECT id, title, prompt, created FROM agent_triggers WHERE kind = 'custom'"),
)
SHAPES = ("round", "square", "tall")
ENGINE = "scheduled"


def _slug(title: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    words = words if words[:1].isalpha() else f"agent-{words}"
    return (words or "agent")[:20].rstrip("-")


def _yours(db: Database, taken: set[str]) -> dict[str, Card]:
    """Each schedule and trigger the person made is an agent with a card of its own."""
    found: dict[str, Card] = {}
    used = set(taken)
    for prefix, query in YOURS:
        for row in db.fetch_all(query):
            identifier = f"{prefix}-{row['id']}"
            handle = _slug(row["title"])
            base, number = handle, 2
            while handle in used:
                handle, number = f"{base[:17]}-{number}", number + 1
            used.add(handle)
            prompt = " ".join(str(row["prompt"] or "").split())
            role = prompt if len(prompt) <= 140 else prompt[:139].rstrip() + "…"
            found[identifier] = Card(
                id=identifier,
                name=row["title"],
                handle=handle,
                role=role or "Runs the instructions you gave it.",
                can_do=(),
                default=False,
                may_assign_to=(),
                talks_to_person=True,
                accepts=("person", "assign", "ask", "note"),
                mascot_style=SHAPES[int(hashlib.sha256(identifier.encode()).hexdigest(), 16) % 3],
                mascot_seed=identifier,
                version=hashlib.sha256(f"{row['title']}\n{prompt}".encode()).hexdigest()[:12],
                kind="yours",
                engine=ENGINE,
                instructions=str(row["prompt"] or ""),
            )
    return found


def card(db: Database, agent: str) -> Card | None:
    return all_cards(db, include_hidden=True).get(agent)


def engine(db: Database, agent: str) -> str:
    """Whose prompt file and tools an agent runs with: itself, or the template it was made from."""
    found = card(db, agent)
    return found.engine if found is not None and found.engine else agent


def name(db: Database, agent: str) -> str:
    """The agent's name, for anything the person or a model reads. Helpers have no card, so
    their id stands in, which is never meant to be shown."""
    found = card(db, agent)
    return found.name if found else agent


def file_default() -> Card:
    """The default card as its file says, for before a Home, and so a database, exists."""
    return next(card for card in _files().values() if card.default)


def default(db: Database) -> Card:
    return next(card for card in all_cards(db).values() if card.default)


def by_handle(db: Database, handle: str) -> Card | None:
    wanted = handle.removeprefix("@").casefold()
    return next((card for card in all_cards(db).values() if card.handle.casefold() == wanted), None)


def resolve(db: Database, recipient: str) -> Card | None:
    """A recipient written by a model or the person: an @handle, a handle or an id."""
    return by_handle(db, recipient) or card(db, recipient.strip())


def addressed(db: Database, text: str) -> tuple[Card | None, str, str | None]:
    """Who a typed message is for, and the message without the @handle. An @ that names no agent
    is left in the text, and comes back as the third value so the person can be told."""
    match = ADDRESSED.match(text)
    if not match:
        return None, text, None
    found = by_handle(db, match.group(1))
    if found is None:
        return None, text, match.group(1)
    return found, text[match.end() :] or text, None


def fill(db: Database, text: str, agent: str) -> str:
    """Puts names into a prompt: {{self.name}}, {{self.handle}}, {{agent.mail.name}}."""
    cards = all_cards(db)

    def value(match: re.Match[str]) -> str:
        target = cards.get(agent if match.group(1) == "self" else match.group(2) or "")
        if target is None:
            return match.group(0)
        return target.name if match.group(3) == "name" else target.at

    return PLACEHOLDER.sub(value, text)


def who_you_are(db: Database, agent: str, skills: list[str] | None = None) -> str:
    """The stable part of the team block. It changes only when a card does, so it can be cached."""
    cards = all_cards(db)
    me = cards.get(agent)
    if me is None:
        return ""
    others = [c for c in cards.values() if c.id != me.id]
    lines = [f"You are {me.name} ({me.at}). {me.role}"]
    if others:
        team = " ".join(f"{c.name} ({c.at}): {c.role}" for c in others)
        lines.append(f"Your team: {team}")
    assignable = [cards[a].at for a in me.may_assign_to if a in cards]
    if assignable:
        lines.append(
            "You may give tasks to: "
            + ", ".join(assignable)
            + ". Do the work yourself unless it stands on its own, with its own inputs and output."
        )
    else:
        lines.append("You don't give tasks to other agents. Do your own work, and report it.")
    if not me.talks_to_person:
        default_card = next(c for c in cards.values() if c.default)
        lines.append(
            f"You don't talk to the person directly unless they write to you. "
            f"{default_card.name} ({default_card.at}) tells them what matters."
        )
    lines += _jobs_lines(cards, me)
    if skills:
        lines.append("Skills you can load with load_skill when one fits the work:")
        lines += [f"- {line}" for line in skills]
    return "\n".join(lines)


def _jobs_lines(cards: dict[str, Card], me: Card) -> list[str]:
    """Which jobs are this agent's alone, and whose the others are, from jobs.py."""
    from nexusai.modules.agent import jobs

    engine = me.engine or me.id
    lines = []
    mine = [job.label for job in jobs.jobs_of(engine)]
    if mine:
        lines.append(f"Yours alone: {'; '.join(mine)}.")
    theirs = [
        f"{job.label} is {cards[job.owner].at}'s"
        for job in jobs.OWNED
        if job.owner != engine and job.handed_over and job.owner in cards
    ]
    if theirs and me.accepts:
        lines.append(f"Not yours: {'; '.join(theirs)}.")
    return lines


def handovers(db: Database, agent: str) -> str:
    """The lead's hand-over table, one row per agent it may give work to, from each agent's
    description, so adding or changing an agent changes the table with it."""
    cards = all_cards(db)
    me = cards.get(agent)
    if me is None:
        return ""
    rows = ["| Work | Who |", "|---|---|"]
    for other in me.may_assign_to:
        found = cards.get(other)
        file = plugins.agent_files().get(found.engine or other) if found else None
        if found is None or file is None:
            continue
        rows.append(f"| {' '.join(file.description.split())} | {found.at} |")
    return "\n".join(rows) if len(rows) > 2 else ""


def to_contract(found: Card, tools: list[str] | None = None) -> AgentCard:
    return AgentCard(
        id=found.id,
        name=found.name,
        handle=found.handle,
        role=found.role,
        can_do=list(found.can_do),
        default=found.default,
        may_assign_to=list(found.may_assign_to),
        talks_to_person=found.talks_to_person,
        accepts=list(found.accepts),
        mascot=AgentMascot(style=found.mascot_style, seed=found.mascot_seed),
        version=found.version,
        renamed=found.renamed,
        kind="yours" if found.kind == "yours" else "built_in",
        tools=tools or [],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def rename(db: Database, agent: str, new_name: str, new_handle: str) -> Card:
    cards = all_cards(db)
    current = cards.get(agent)
    if current is None:
        raise CommandError("agent.not_found", "There's no agent with that id.", 404)
    new_handle = new_handle.casefold()
    taken = next((c for c in cards.values() if c.id != agent and c.handle == new_handle), None)
    if taken is not None:
        raise CommandError(
            "agent.handle_taken", f"@{new_handle} already belongs to {taken.name}.", 409
        )
    taken = next(
        (c for c in cards.values() if c.id != agent and c.name.casefold() == new_name.casefold()),
        None,
    )
    if taken is not None:
        raise CommandError("agent.name_taken", f"Another agent is already called {new_name}.", 409)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_card_overrides (id, name, handle, updated) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET name = excluded.name, handle = excluded.handle,"
            " updated = excluded.updated",
            (agent, new_name if current.kind == "built_in" else None, new_handle, _now()),
        )
        if current.kind == "yours":
            # Its title is its name, so the schedule or trigger itself is renamed.
            table = "schedules" if agent.startswith("schedule-") else "agent_triggers"
            tx.execute(
                f"UPDATE {table} SET title = ? WHERE id = ?",  # noqa: S608
                (new_name, agent.split("-", 1)[1]),
            )
    sync(db)
    return all_cards(db)[agent]


def reset_name(db: Database, agent: str) -> Card:
    current = card(db, agent)
    original = _files().get(agent)
    if current is not None and current.kind == "yours":
        raise CommandError(
            "agent.not_built_in", "This agent is yours, so its name is the one you gave it.", 409
        )
    if current is None or original is None:
        raise CommandError("agent.not_found", "There's no agent with that id.", 404)
    taken = next(
        (c for c in all_cards(db).values() if c.id != agent and c.handle == original.handle),
        None,
    )
    if taken is not None:
        raise CommandError(
            "agent.handle_taken",
            f"@{original.handle} now belongs to {taken.name}. Rename that agent first.",
            409,
        )
    with db.transaction() as tx:
        tx.execute(
            "UPDATE agent_card_overrides SET name = NULL, handle = NULL, updated = ? WHERE id = ?",
            (_now(), agent),
        )
    sync(db)
    return all_cards(db)[agent]


def set_mascot(db: Database, agent: str, seed: str) -> Card:
    if card(db, agent) is None:
        raise CommandError("agent.not_found", "There's no agent with that id.", 404)
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO agent_card_overrides (id, mascot_seed, updated) VALUES (?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET mascot_seed = excluded.mascot_seed,"
            " updated = excluded.updated",
            (agent, seed, _now()),
        )
    return all_cards(db)[agent]


# The rows an agent owns and titles after itself. Suffixes describe the run, never the agent. The
# brief's schedule is named for the brief, not for the agent that writes it.
BUILT_IN_TITLES = (
    ("agent_sessions", "id = 'mail-agent'", "mail", ""),
    ("agent_sessions", "agent = 'interview'", "interview", ""),
    ("agent_triggers", "id = 'mail-received'", "mail", ", on new mail"),
    ("schedules", "kind = 'mail-hourly'", "mail", ", hourly"),
)


def sync(db: Database) -> None:
    """Gives built-in chats, schedules and triggers their agent's current name. Runs at startup
    and after every rename, so a name changed in a card file reaches existing data too."""
    cards = all_cards(db)
    with db.transaction() as tx:
        for table, where, agent, suffix in BUILT_IN_TITLES:
            found = cards.get(agent)
            if found is not None:
                tx.execute(
                    f"UPDATE {table} SET title = ? WHERE {where}",  # noqa: S608
                    (found.name + suffix,),
                )
