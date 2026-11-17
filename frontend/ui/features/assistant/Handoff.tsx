"use client";

import { useState } from "react";
import type { TeamTask } from "@/ui/client/contracts.generated";
import { clockText } from "@/ui/client/format";
import { useAgentCards, useTeamTask } from "@/ui/client/work";
import { Icon, type IconName } from "@/ui/icons";
import { LiveDot } from "@/ui/primitives/LiveDot";
import { Reveal, Turn } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { TextLink } from "@/ui/primitives/TextLink";
import { t, type StringKey } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";
import { isFinished, type ToolPart } from "./parts";
import { toolStep } from "./ThinkingTrace";

// team_assign names the task it gave, whether it says it was given or brings back the report.
const TASK = /\btask (\d+)\b/i;
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

type Shown = { live?: "running" | "waiting"; icon?: IconName; tone: string; label: StringKey; breathes?: boolean };

// How each state of a task reads on its one line. Colour never carries it alone: there's a word too.
const STATES: Readonly<Record<string, Shown>> = {
  handing: { live: "running", tone: "text-agent-running", label: "handoff.state.handing", breathes: true },
  queued: { tone: "text-ink-muted", label: "handoff.state.queued" },
  working: { live: "running", tone: "text-agent-running", label: "handoff.state.working", breathes: true },
  input_required: { live: "waiting", tone: "text-agent-waiting", label: "handoff.state.asked" },
  blocked: { icon: "error", tone: "text-agent-waiting", label: "handoff.state.paused" },
  reported: { icon: "check", tone: "text-agent-done", label: "handoff.state.reported" },
  verified: { icon: "check", tone: "text-agent-done", label: "handoff.state.checked" },
  rejected: { icon: "error", tone: "text-agent-failed", label: "handoff.state.rejected" },
  failed: { icon: "error", tone: "text-agent-failed", label: "handoff.state.stopped" },
  canceled: { icon: "error", tone: "text-ink-muted", label: "handoff.state.canceled" },
  refused: { icon: "error", tone: "text-agent-failed", label: "handoff.state.notGiven" },
};

const OPEN = new Set(["queued", "working", "input_required"]);

function elapsed(task: TeamTask) {
  const end = OPEN.has(task.state) ? Date.now() : new Date(task.updated).getTime();
  return clockText((end - new Date(task.created).getTime()) / 1000);
}

/** A hand-over as one quiet line that shows it's alive, opening to what it's doing. */
export function HandoffCard({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false);
  const assistant = useAssistant();
  const cards = useAgentCards().data?.cards ?? [];
  const input = part.input ?? {};
  const to = String(input.to ?? "").replace(/^@/, "");
  const card = cards.find((item) => item.handle === to || item.id === to);
  const output = typeof part.output === "string" ? part.output : null;
  const given = output && !output.startsWith("Not ") ? TASK.exec(output) : null;
  const task = useTeamTask(given ? Number(given[1]) : null).data;
  const row = task?.task;
  const refused = part.state === "output-denied" || part.state === "output-error" || Boolean(output?.startsWith("Not "));
  const state = refused ? "refused" : !isFinished(part) || !row ? "handing" : row.state;
  const shown = STATES[state] ?? STATES.queued!;
  const objective = String(input.objective ?? "");
  const working = state === "working";
  return (
    <div data-testid="handoff-card" data-state={state}>
      <Pressable aria-expanded={open} onClick={() => setOpen((value) => !value)} className="focus-ring flex w-full items-center gap-2 rounded-md border border-line-subtle bg-surface-raised px-3 py-2 text-left text-md transition-colors duration-fast hover:bg-surface-sunken">
        <span className="flex w-3 shrink-0 justify-center">
          {shown.live ? <LiveDot tone={shown.live} /> : shown.icon ? <Icon name={shown.icon} className={`h-3 w-3 ${shown.tone}`} /> : <span className="h-2 w-2 rounded-full border border-line-strong" />}
        </span>
        <span className="shrink-0 font-medium text-ink-primary">{card?.name ?? to}</span>
        <span className="min-w-0 flex-1 truncate text-ink-secondary">{objective}</span>
        <span className={`shrink-0 text-sm ${shown.tone} ${shown.breathes ? "animate-working motion-reduce:animate-none" : ""}`}>{t(shown.label)}</span>
        <Turn open={open}>
          <Icon name="chevronRight" className="h-3 w-3 text-ink-faint" />
        </Turn>
      </Pressable>
      <Reveal open={open}>
        <div className="ml-3 mt-2 flex flex-col gap-2 border-l border-line-subtle py-1 pl-3 text-sm">
          {refused && output ? <p className="text-status-danger">{output}</p> : null}
          {part.errorText ? <p className="text-status-danger">{part.errorText}</p> : null}
          <dl className="flex flex-col gap-1 text-ink-secondary">
            {input.done_criteria ? <div className="flex gap-3"><dt className="shrink-0 text-ink-muted">{t("handoff.doneWhen")}</dt><dd>{String(input.done_criteria)}</dd></div> : null}
            {row ? <div className="flex gap-3"><dt className="shrink-0 text-ink-muted">{t("handoff.task")}</dt><dd className="font-mono tabular-nums">{t("handoff.taskLine", { id: row.id, time: elapsed(row), tokens: compact.format(row.tokens_used ?? 0) })}</dd></div> : null}
          </dl>
          {task?.steps?.length ? (
            <ol className="flex flex-col gap-1">
              {task.steps.map((step, index) => {
                const look = toolStep(step.tool, step.input);
                const last = index === task.steps!.length - 1;
                return (
                  <li key={`${step.started}-${index}`} className="flex min-w-0 items-center gap-2 text-ink-secondary">
                    {working && last ? <LiveDot /> : <Icon name={step.status === "refused" ? "error" : look.icon} className="h-3 w-3 shrink-0 text-ink-muted" />}
                    <span className="shrink-0">{look.label}</span>
                    {look.chip ? <span className="min-w-0 truncate rounded-sm bg-surface-sunken px-1 font-mono text-ink-muted">{look.chip}</span> : null}
                  </li>
                );
              })}
            </ol>
          ) : null}
          {row?.outcome ? <p className="text-ink-secondary">{row.outcome}</p> : null}
          <div className="flex flex-wrap gap-4">
            {row?.owner_session ? <Pressable onClick={() => assistant.openSession(row.owner_session as string)} className="focus-ring rounded-sm text-accent-default underline-offset-2 hover:underline">{t("handoff.openRun")}</Pressable> : null}
            <TextLink href="/agent/channel?tab=tasks">{t("handoff.teamTasks")}</TextLink>
          </div>
        </div>
      </Reveal>
    </div>
  );
}

/** Above the message box while hand-overs from this chat are still going, so it never looks idle. */
export function TeamWorkingLine({ tasks }: { tasks: readonly TeamTask[] }) {
  const cards = useAgentCards().data?.cards ?? [];
  if (!tasks.length) return null;
  const owners = [...new Set(tasks.map((task) => task.owner))];
  const name = cards.find((card) => card.id === owners[0])?.name ?? owners[0] ?? "";
  const waiting = tasks.every((task) => task.state === "input_required");
  return (
    <p data-testid="team-working" role="status" className="flex items-center gap-2 px-1 text-sm text-ink-muted">
      <LiveDot tone={waiting ? "waiting" : "running"} />
      {owners.length === 1 ? t(tasks.length === 1 ? "handoff.working.one" : "handoff.working.many", { agent: name, count: tasks.length }) : t("handoff.working.team", { count: tasks.length })}
    </p>
  );
}
