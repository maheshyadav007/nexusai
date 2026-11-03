"""Everything an agent is told about the person. The run and the page showing it use the same code."""

import re
from typing import Any

from nexusai.contracts.agent import AgentKnowledge, KnowledgeLayer, LearnedNote, MailPreview
from nexusai.kernel.module import Context
from nexusai.modules.agent import feedback, mail_agent, memory, prompts_builder, signals
from nexusai.modules.agent import guard as guards
from nexusai.modules.agent.gateway import Layer
from nexusai.modules.agent.guard import DataGuard
from nexusai.modules.settings.module import load_profile

NOTE = re.compile(r"^- (?P<text>.*?)(?: \[mail:(?P<thread>\d+)\])?$")
CHARS_PER_TOKEN = 4
# What each layer is, in the order the model reads it, and how far to trust it.
TRUST = {
    "System prompt": "built-in",
    "Agent prompt": "built-in",
    "About the person": "yours",
    "Personalized prompts": "yours",
    "What you corrected": "yours",
    "How they want the brief": "yours",
    "What the mailbox shows": "counted",
    "Memory": "mixed",
}


def about_person(ctx: Context) -> str:
    """From Settings. Every agent reads it, because it's the person's own words about themselves."""
    profile = load_profile(ctx)
    addresses = sorted(signals.own_addresses(ctx))
    lines = [
        f"Name: {profile.name}" if profile.name else "",
        f"Role: {profile.role}" if profile.role else "",
        f"Their mail addresses: {', '.join(addresses)}" if addresses else "",
        f"People who matter most to them, in their own words:\n{profile.vips}"
        if profile.vips
        else "",
        f"About them, in their own words:\n{profile.about}" if profile.about else "",
        f"Their signature:\n{profile.signature}" if profile.signature else "",
    ]
    said = "\n".join(line for line in lines if line)
    return f"{said}\nTone for anything written as them: {profile.tone}" if said else ""


def layers_for(
    ctx: Context, agent: str, task_text: str, capabilities: str = "", **values: str
) -> list[Layer]:
    config = ctx.config
    is_mail = agent == mail_agent.AGENT
    return prompts_builder.build_layers(
        config,
        agent,
        memory=memory.relevant(config.home, agent, task_text, config.agent.memory_max_chars),
        capabilities=capabilities,
        about=about_person(ctx),
        corrections=feedback.layer(ctx.bus.db) if is_mail else "",
        brief_wishes=feedback.brief_layer(ctx.bus.db) if agent == "daily-prep" else "",
        mailbox=signals.mailbox_layer(ctx) if is_mail else "",
        **values,
    )


def _notes(ctx: Context) -> list[LearnedNote]:
    notes: list[LearnedNote] = [
        LearnedNote(line=line, text=line.lstrip("- "), section="", thread=None, confirmed=True)
        for line in memory.confirmed(ctx.config.home).splitlines()
        if line.strip()
    ]
    section = ""
    for line in memory.learned(ctx.config.home).splitlines():
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
            continue
        found = NOTE.match(line.strip())
        if found:
            thread = found.group("thread")
            notes.append(
                LearnedNote(
                    line=line,
                    text=found.group("text"),
                    section=section,
                    thread=int(thread) if thread else None,
                )
            )
    return notes


def _shown(layers: list[Layer]) -> list[KnowledgeLayer]:
    return [
        KnowledgeLayer(name=layer.name, text=layer.text, trust=TRUST.get(layer.name, "built-in"))
        for layer in layers
    ]


def view(ctx: Context) -> AgentKnowledge:
    db = ctx.bus.db
    # The same layers as a real run, with no email in hand, and the whole of what's kept.
    layers = layers_for(ctx, mail_agent.AGENT, "", "", scratch="your scratch folder")
    judged = db.fetch_all("SELECT COUNT(*) AS n FROM triage_runs WHERE status = 'done'")[0]["n"]
    done, total = mail_agent.learning_progress(ctx)
    return AgentKnowledge(
        brief_reactions=feedback.brief_reactions(db),
        layers=_shown(layers),
        notes=_notes(ctx),
        corrections=feedback.recent(db),
        contacts=signals.contacts(ctx),
        judged=judged,
        learning_state=mail_agent.learning_state(ctx),
        learning_done=done,
        learning_total=total,
        conversations_unread=mail_agent.conversations_not_read(ctx),
    )


def preview(ctx: Context, thread: int) -> MailPreview:
    """Exactly what the model would be sent for this conversation, masked as it would be going
    out. Calls no model."""
    subject, _, task = mail_agent.task_for(ctx, thread)
    layers = layers_for(
        ctx, mail_agent.AGENT, f"{subject}\n{task}", "", scratch="your scratch folder"
    )
    masking = DataGuard(ctx.bus.db, guards.load_rules(ctx.config.home))
    masked = [Layer(layer.name, masking.mask(layer.text)) for layer in layers]
    return MailPreview(
        layers=_shown(masked),
        given=masking.mask(task),
        instruction=mail_agent.live_instruction(),
        approx_tokens=_tokens(layers, task),
    )


def _tokens(layers: list[Any], task: str) -> int:
    return (sum(len(layer.text) for layer in layers) + len(task)) // CHARS_PER_TOKEN
