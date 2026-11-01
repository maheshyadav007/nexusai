"use client";

import { useEffect, useRef, useState } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { t, tn, type StringKey } from "@/ui/strings";
import { isFinished, toolName, type ToolPart } from "./parts";
import { Reveal, Swap, Turn } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";

type Step = ToolPart | { type: "reasoning"; text: string };

const isTool = (step: Step): step is ToolPart => step.type !== "reasoning";

const TOOL_SHOWN: Readonly<Record<string, { label: StringKey; icon: IconName; chip?: string }>> = {
  list_folder: { label: "tool.list_folder", icon: "folder", chip: "path" },
  read_file: { label: "tool.read_file", icon: "file", chip: "path" },
  write_file: { label: "tool.write_file", icon: "drafts", chip: "path" },
  edit_file: { label: "tool.edit_file", icon: "drafts", chip: "path" },
  move_file: { label: "tool.move_file", icon: "drafts", chip: "destination" },
  delete_file: { label: "tool.delete_file", icon: "trash", chip: "path" },
  run_command: { label: "tool.run_command", icon: "sessions", chip: "command" },
  search_mail: { label: "tool.search_mail", icon: "search", chip: "query" },
  read_thread: { label: "tool.read_thread", icon: "inbox", chip: "thread_id" },
  list_mail: { label: "tool.list_mail", icon: "inbox", chip: "folder" },
  update_mail: { label: "tool.update_mail", icon: "inbox", chip: "thread_ids" },
  trash_mail: { label: "tool.trash_mail", icon: "trash", chip: "thread_ids" },
  list_drafts: { label: "tool.list_drafts", icon: "drafts" },
  delete_drafts: { label: "tool.delete_drafts", icon: "drafts", chip: "draft_ids" },
  list_categories: { label: "tool.list_categories", icon: "categories" },
  update_category: { label: "tool.update_category", icon: "categories", chip: "name" },
  delete_categories: { label: "tool.delete_categories", icon: "categories", chip: "names" },
  merge_categories: { label: "tool.merge_categories", icon: "categories", chip: "into" },
  reorder_categories: { label: "tool.reorder_categories", icon: "categories" },
  list_rules: { label: "tool.list_rules", icon: "categories" },
  save_rule: { label: "tool.save_rule", icon: "categories", chip: "name" },
  delete_rules: { label: "tool.delete_rules", icon: "categories", chip: "names" },
  search_documents: { label: "tool.search_documents", icon: "documents", chip: "query" },
  list_documents: { label: "tool.list_documents", icon: "documents" },
  read_document: { label: "tool.read_document", icon: "documents", chip: "key" },
  update_documents: { label: "tool.update_documents", icon: "documents", chip: "keys" },
  delete_documents: { label: "tool.delete_documents", icon: "documents", chip: "keys" },
  read_database: { label: "tool.read_database", icon: "search", chip: "sql" },
  list_tasks: { label: "tool.list_tasks", icon: "tasks" },
  update_tasks: { label: "tool.update_tasks", icon: "tasks", chip: "changes" },
  delete_tasks: { label: "tool.delete_tasks", icon: "tasks", chip: "task_ids" },
  list_reminders: { label: "tool.list_reminders", icon: "reminders" },
  update_reminders: { label: "tool.update_reminders", icon: "reminders", chip: "changes" },
  delete_reminders: { label: "tool.delete_reminders", icon: "reminders", chip: "reminder_ids" },
  list_agents: { label: "tool.list_agents", icon: "agent" },
  update_agent: { label: "tool.update_agent", icon: "agent", chip: "name" },
  run_agent: { label: "tool.run_agent", icon: "agent", chip: "agent_id" },
  remove_agents: { label: "tool.remove_agents", icon: "agent", chip: "agent_ids" },
  list_memory: { label: "tool.list_memory", icon: "memory" },
  update_memory: { label: "tool.update_memory", icon: "memory", chip: "path" },
  forget_memory: { label: "tool.forget_memory", icon: "memory", chip: "paths" },
  list_panels: { label: "tool.list_panels", icon: "panels" },
  save_panel: { label: "tool.save_panel", icon: "panels", chip: "title" },
  remove_panels: { label: "tool.remove_panels", icon: "panels", chip: "panel_ids" },
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

/** A value or a count, so a long list in a tool's input stays one short chip. */
const chipText = (value: unknown) => (Array.isArray(value) ? tn("tool.items", value.length) : String(value));

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
      <Pressable aria-expanded={open} onClick={() => setOpen((current) => !current)} className="focus-ring group flex w-full items-center gap-2 rounded-sm py-1 text-left text-md text-ink-secondary transition-colors duration-fast hover:text-ink-primary">
        <Icon name={failed ? "error" : (shown?.icon ?? "customize")} className={`h-3 w-3 shrink-0 ${failed ? "text-status-danger" : "text-ink-muted"}`} />
        <span className="shrink-0">{stepLabel(part)}</span>
        {chip !== undefined && chip !== null && chip !== "" ? <span className="min-w-0 truncate rounded-sm bg-surface-sunken px-1 font-mono text-sm text-ink-muted">{chipText(chip)}</span> : null}
        {denied ? <span className="shrink-0 text-sm text-ink-muted">{t("tools.state.denied")}</span> : null}
        {!isFinished(part) ? <span className="h-1 w-1 shrink-0 animate-working rounded-full bg-agent-running motion-reduce:animate-none" /> : null}
      </Pressable>
      <Reveal open={open}>
            <div className="mb-2 mt-1 flex flex-col gap-2">
              {part.input && Object.keys(part.input).length ? <pre className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{asText(part.input)}</pre> : null}
              {part.output !== undefined ? <pre data-testid="tool-output" className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{asText(part.output)}</pre> : null}
              {part.errorText ? <p className="text-sm text-status-danger">{part.errorText}</p> : null}
            </div>
          </Reveal>
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
      <Pressable aria-expanded={open} onClick={() => setOpen((value) => !value)} className="focus-ring flex items-center gap-2 rounded-sm py-1 text-md text-ink-muted transition-colors duration-fast hover:text-ink-primary">
        <Icon name="thinking" className={`h-4 w-4 shrink-0 ${running ? "animate-working motion-reduce:animate-none" : ""}`} />
        <Swap value={running ? (current ? stepLabel(current) : t("chat.thinking")) : summary}>{running ? (current ? stepLabel(current) : t("chat.thinking")) : summary}</Swap>
        {tools.length && !active ? <span className="text-sm tabular-nums text-ink-faint">{tn("chat.steps", tools.length)}</span> : null}
        <Turn open={open}>
          <Icon name="chevronRight" className="h-3 w-3" />
        </Turn>
      </Pressable>
      <Reveal open={open}>
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
          </Reveal>
    </div>
  );
}
