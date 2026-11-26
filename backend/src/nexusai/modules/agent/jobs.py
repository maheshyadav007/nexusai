"""Jobs that belong to one agent. Every other agent is kept from their tools, and told whose they are.

A job is a named group of tools. Most work is shared: any agent whose tool set allows it may do it.
A job listed here has one owner, so a weak model given two ways to do it can't take the wrong one,
and a call from anyone else is answered with "That's @owner's job, hand it over". The owner table is
the one place this is decided; prompts, tool errors and find_tools read it. See
docs/AGENT_OWNERS_PLAN.md and docs/PLUGIN_FORMAT_PLAN.md §8.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    name: str
    owner: str
    tools: frozenset[str]
    # What the job is, in a few words, for the prompt and the Agents page.
    label: str
    # Whether others hand this work to its owner. Suggestions aren't handed over: anyone who may
    # act makes the thing itself.
    handed_over: bool = True


OWNED = (
    Job(
        "triage",
        "mail",
        frozenset({"record_triage", "save_what_i_learned"}),
        "reading each email and recording what it holds",
    ),
    Job(
        "mail-suggestions",
        "mail",
        frozenset({"propose_task", "propose_reminder"}),
        "suggesting tasks and reminders from mail for the person to keep",
        handed_over=False,
    ),
    Job(
        "brief",
        "daily-prep",
        frozenset({"read_plate", "update_brief"}),
        "the brief on Today",
    ),
)
JOBS = {job.name: job for job in OWNED}


def owned_tools() -> dict[str, Job]:
    """Each owned tool and its job. A tool is in one job at most."""
    found: dict[str, Job] = {}
    for job in OWNED:
        for tool in job.tools:
            if tool in found:
                raise ValueError(f"{tool} is in two jobs: {found[tool].name} and {job.name}")
            found[tool] = job
    return found


def withheld_for(agent: str) -> frozenset[str]:
    """The tools of every job another agent owns."""
    return frozenset(tool for tool, job in owned_tools().items() if job.owner != agent)


def jobs_of(agent: str) -> list[Job]:
    return [job for job in OWNED if job.owner == agent]


def handed_over_tools(agent: str) -> dict[str, str]:
    """Each tool this agent is kept from that it should hand over, and the owner's id."""
    return {
        tool: job.owner
        for tool, job in owned_tools().items()
        if job.owner != agent and job.handed_over
    }
