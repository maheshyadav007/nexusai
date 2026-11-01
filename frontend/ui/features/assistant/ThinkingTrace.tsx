"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { QUICK, REVEAL } from "@/ui/primitives/motion";
import { t, tn, type StringKey } from "@/ui/strings";
import { isFinished, toolName, type ToolPart } from "./parts";

type Step = ToolPart | { type: "reasoning"; text: string };

const isTool = (step: Step): step is ToolPart => step.type !== "reasoning";

const TOOL_SHOWN: Readonly<Record<string, { label: StringKey; icon: IconName; chip?: string }>> = {
  read_file: { label: "tool.read_file", icon: "file", chip: "path" },
  write_file: { label: "tool.write_file", icon: "drafts", chip: "path" },
  edit_file: { label: "tool.edit_file", icon: "drafts", chip: "path" },
  run_command: { label: "tool.run_command", icon: "sessions", chip: "command" },
  search_mail: { label: "tool.search_mail", icon: "search", chip: "query" },
  read_thread: { label: "tool.read_thread", icon: "inbox", chip: "thread_id" },
  list_mail: { label: "tool.list_mail", icon: "inbox", chip: "folder" },
  list_categories: { label: "tool.list_categories", icon: "categories" },
  set_thread_category: { label: "tool.set_thread_category", icon: "categories", chip: "category" },
  archive_thread: { label: "tool.archive_thread", icon: "archive", chip: "thread_id" },
  search_documents: { label: "tool.search_documents", icon: "documents", chip: "query" },
  read_document: { label: "tool.read_document", icon: "documents", chip: "key" },
  read_database: { label: "tool.read_database", icon: "search", chip: "sql" },
  list_tasks: { label: "tool.list_tasks", icon: "tasks" },
  complete_task: { label: "tool.complete_task", icon: "tasks", chip: "task_id" },
  list_reminders: { label: "tool.list_reminders", icon: "reminders" },
  list_agents: { label: "tool.list_agents", icon: "agent" },
  remove_agent: { label: "tool.remove_agent", icon: "agent", chip: "agent_id" },
  read_work_board: { label: "tool.read_work_board", icon: "tasks" },
  write_work_board: { label: "tool.write_work_board", icon: "tasks", chip: "title" },
  post_to_agents: { label: "tool.post_to_agents", icon: "channel", chip: "topic" },
  read_agent_messages: { label: "tool.read_agent_messages", icon: "channel" },
  propose_memory: { label: "tool.propose_memory", icon: "memory" },
  save_personal_prompt: { label: "tool.save_personal_prompt", icon: "memory", chip: "name" },
  suggest: { label: "tool.suggest", icon: "channel" },
  tell: { label: "tool.tell", icon: "channel" },
  notify_person: { label: "tool.notify_person", icon: "notifications" },
};

const asText = (value: unknown) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

const stepLabel = (part: ToolPart) => {
  const shown = TOOL_SHOWN[toolName(part)];
  return shown ? t(shown.label) : toolName(part).replaceAll("_", " ");
};

function ToolRow({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false);
  const shown = TOOL_SHOWN[toolName(part)];
  const chip = shown?.chip ? part.input?.[shown.chip] : undefined;
  const failed = part.state === "output-error";
  const denied = part.state === "output-denied";
  return (
    <li data-testid="tool-call">
      <button type="button" aria-expanded={open} onClick={() => setOpen((current) => !current)} className="focus-ring group flex w-full items-center gap-2 rounded-sm py-1 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
        <Icon name={failed ? "error" : (shown?.icon ?? "customize")} className={`h-3 w-3 shrink-0 ${failed ? "text-status-danger" : "text-ink-muted"}`} />
        <span className="shrink-0">{stepLabel(part)}</span>
        {chip !== undefined && chip !== null && chip !== "" ? <span className="min-w-0 truncate rounded-sm bg-surface-sunken px-1 font-mono text-sm text-ink-muted">{String(chip)}</span> : null}
        {denied ? <span className="shrink-0 text-sm text-ink-muted">{t("tools.state.denied")}</span> : null}
        {!isFinished(part) ? <span className="h-1 w-1 shrink-0 animate-working rounded-full bg-agent-running motion-reduce:animate-none" /> : null}
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div {...REVEAL} className="overflow-hidden">
            <div className="mb-2 mt-1 flex flex-col gap-2">
              {part.input && Object.keys(part.input).length ? <pre className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{asText(part.input)}</pre> : null}
              {part.output !== undefined ? <pre data-testid="tool-output" className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{asText(part.output)}</pre> : null}
              {part.errorText ? <p className="text-sm text-status-danger">{part.errorText}</p> : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

/** How the agent got to its answer: one quiet line, which opens into each step it took. */
export function ThinkingTrace({ steps, running }: { steps: readonly Step[]; running: boolean }) {
  const [open, setOpen] = useState(false);
  const began = useRef(Date.now());
  const [seconds, setSeconds] = useState<number | null>(null);
  useEffect(() => {
    if (running) return () => setSeconds(Math.max(1, Math.round((Date.now() - began.current) / 1000)));
    return undefined;
  }, [running]);
  const tools = steps.filter(isTool);
  const active = running && tools.some((part) => !isFinished(part));
  const current = [...tools].reverse().find((part) => !isFinished(part));
  const summary = seconds ? t("chat.thoughtFor", { seconds }) : t("chat.thought");
  return (
    <div data-testid="thinking">
      <button type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)} className="focus-ring flex items-center gap-2 rounded-sm py-1 text-md text-ink-muted transition-colors duration-fast hover:text-ink-primary">
        <Icon name="thinking" className={`h-4 w-4 shrink-0 ${running ? "animate-working motion-reduce:animate-none" : ""}`} />
        <span>{running ? (current ? stepLabel(current) : t("chat.thinking")) : summary}</span>
        {tools.length && !active ? <span className="text-sm tabular-nums text-ink-faint">{tn("chat.steps", tools.length)}</span> : null}
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={QUICK} className="inline-flex">
          <Icon name="chevronRight" className="h-3 w-3" />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div {...REVEAL} className="overflow-hidden">
            <ul className="ml-2 mt-1 flex flex-col border-l border-line-subtle pl-3">
              {steps.map((step, index) =>
                isTool(step) ? (
                  <ToolRow key={step.toolCallId} part={step} />
                ) : (
                  <li key={index} className="whitespace-pre-wrap py-1 text-md text-ink-muted">
                    {step.text}
                  </li>
                ),
              )}
            </ul>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
