"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { ContextSettings, SaveTrigger, GetCockpitEvents, MailAgentSettings, QuietHours, Schedule, SaveMemory, SavePrompt, SaveReminder, SaveTask, SendCheckSettings, SetSessionContext, GuardRules, SaveModelProvider, ListProviderModels } from "./contracts.generated";
import { useHomeReady } from "./home";
import { useCategories } from "./mail";
import { useApprovals } from "./sessions";

function useReady<T>(key: readonly unknown[], fn: () => Promise<T>) {
  const ready = useHomeReady();
  return useQuery({ queryKey: key, queryFn: fn, enabled: ready });
}

function useCommand<I, R>(keys: readonly string[], run: (input: I) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      for (const key of keys) void client.invalidateQueries({ queryKey: [key] });
    },
  });
}

export const useToday = () => useReady(["today"], () => query("today.view", {}));
export const useChannel = () => useReady(["channel"], () => query("channel.list", {}));
export const useRespondChannel = () => useCommand(["channel"], (input: { id: number; answer: string }) => command("channel.respond", input));
export const useDismissChannel = () => useCommand(["channel"], (id: number) => command("channel.dismiss", { id }));
export const useBoard = () => useReady(["board"], () => query("board.list", {}));
export const useAgentChannel = () => useReady(["agent-channel"], () => query("agentChannel.list", {}));
export const useMuteTopic = () => useCommand(["agent-channel"], (input: { topic: string; muted: boolean }) => command("agentChannel.setMuted", input));

export const useTasks = (includeDone: boolean) => useReady(["tasks", includeDone], () => query("tasks.list", { include_done: includeDone }));
export const useSaveTask = () => useCommand(["tasks"], (input: SaveTask) => command("tasks.save", input));
export const useRemoveTask = () => useCommand(["tasks"], (id: number) => command("tasks.remove", { id }));
export const useReminders = () => useReady(["reminders"], () => query("reminders.list", {}));
export const useSaveReminder = () => useCommand(["reminders"], (input: SaveReminder) => command("reminders.save", input));
export const useSnooze = () => useCommand(["reminders"], (input: { id: number; minutes: number }) => command("reminders.snooze", input));
export const useRemoveReminder = () => useCommand(["reminders"], (id: number) => command("reminders.remove", { id }));

export const useSchedules = () => useReady(["schedules"], () => query("schedules.list", {}));
export const useSaveSchedule = () => useCommand(["schedules"], (input: Schedule) => command("schedules.save", input));
export const useRemoveSchedule = () => useCommand(["schedules"], (id: number) => command("schedules.remove", { id }));
export const useRunSchedule = () => useCommand(["schedules"], (id: number) => command("schedules.runNow", { id }));
export const useSetDefaults = () => useCommand(["schedules"], (input: { time_check_enabled?: boolean; live_mail_enabled?: boolean }) => command("schedules.setDefaults", input));

export const useMailAgent = () => useReady(["mail-agent"], () => query("mailAgent.get", {}));
export const useSaveMailAgent = () => useCommand(["mail-agent"], (input: MailAgentSettings) => command("mailAgent.save", input));
export const useKnowledge = () => useReady(["knowledge"], () => query("mailAgent.knowledge", {}));
export const useMailPreview = (thread: number | null) => useQuery({ queryKey: ["mail-preview", thread], queryFn: () => query("mailAgent.preview", { thread: thread as number }), enabled: thread !== null, staleTime: 0 });
export const useReadMore = () => useCommand(["knowledge", "mail-agent", "cockpit"], (count: number) => command("mailAgent.readMore", { count }));
export const useConfirmNote = () => useCommand(["knowledge", "memory"], (line: string) => command("memory.confirmNote", { line }));
export const useRemoveNote = () => useCommand(["knowledge", "memory"], (line: string) => command("memory.removeNote", { line }));
export const useSuggestions = () => useReady(["suggestions"], () => query("suggestions.list", {}));
export const useDecideSuggestion = () => useCommand(["suggestions", "today", "threads", "categories"], (input: { id: number; accept: boolean }) => command("suggestions.decide", input));
export const useRunMailAgent = () => useCommand(["sessions"], () => command("mailAgent.runNow", {}));
export const useContextSettings = () => useReady(["context"], () => query("context.get", {}));
export const useSaveContextSettings = () => useCommand(["context"], (input: ContextSettings) => command("context.save", input));
export const useCompactSession = () => useCommand(["session"], (id: string) => command("session.compact", { id }));

export const useMarkTodaySeen = () => useMutation({ mutationFn: () => command("today.markSeen", {}) });
export const useTriggers = () => useReady(["triggers"], () => query("triggers.list", {}));
export const useSaveTrigger = () => useCommand(["triggers"], (input: SaveTrigger) => command("triggers.save", input));
export const useRemoveTrigger = () => useCommand(["triggers"], (id: string) => command("triggers.remove", { id }));
export const useJobs = () => useReady(["jobs"], () => query("jobs.list", {}));
export const useCockpit = () => useReady(["cockpit"], () => query("cockpit.view", {}));
export const useCockpitEvents = (filter: NonNullable<GetCockpitEvents["filter"]>) => useReady(["cockpit-events", filter], () => query("cockpit.events", { filter }));
// A check that finds nothing announces nothing, so one timer reads the list just after the next is due.
const AFTER_CHECK_MS = 5_000;
export function usePipelines() {
  const ready = useHomeReady();
  return useQuery({
    queryKey: ["pipelines"],
    queryFn: () => query("pipelines.list", {}),
    enabled: ready,
    refetchInterval: (found) => {
      const due = (found.state.data?.pipelines ?? []).flatMap((row) => (row.next_run ? [Date.parse(row.next_run)] : []));
      return due.length ? Math.max(Math.min(...due) - Date.now(), 0) + AFTER_CHECK_MS : false;
    },
  });
}
export const usePausePipeline = () => useCommand(["pipelines", "mail-status", "cockpit"], (input: { id: string; paused: boolean }) => command("pipelines.pause", input));
export const useStopPipeline = () => useCommand(["pipelines", "mail-status", "cockpit"], (id: string) => command("pipelines.stop", { id }));
export const usePipelineMore = () => useCommand(["pipelines", "mail-status", "cockpit"], (input: { id: string; count: number | null }) => command("pipelines.more", input));
export const useRunPipeline = () => useCommand(["pipelines"], (id: string) => command("pipelines.run", { id }));
export const useActivity = () => useReady(["activity"], () => query("activity.list", {}));
export const useUndo = () => useCommand(["activity"], (id: number) => command("activity.undo", { id }));

export const usePrompts = () => useReady(["prompts"], () => query("prompts.list", {}));
export const useSavePrompt = () => useCommand(["prompts"], (input: SavePrompt) => command("prompts.save", input));
export const useStarterPrompts = () => useCommand(["prompts"], () => command("prompts.useStarters", {}));
export const useMemory = (search: string) => useReady(["memory", search], () => query("memory.list", { query: search }));
export const useSaveMemory = () => useCommand(["memory"], (input: SaveMemory) => command("memory.save", input));
export const useRemoveMemory = () => useCommand(["memory"], (path: string) => command("memory.remove", { path }));
export const useDecideMemory = () => useCommand(["memory"], (input: { id: number; accept: boolean }) => command("memory.decide", input));

export const useThreadSummary = (id: number) => useReady(["summary", id], () => query("thread.summary", { id }));
export const useSummarize = () => useCommand(["summary"], (id: number) => command("thread.summarize", { id }));
export const useThreadRuns = (thread: number, enabled: boolean) => useQuery({ queryKey: ["runs", thread], queryFn: () => query("triage.runs", { thread }), enabled, staleTime: 0 });
export const useTriageEstimate = () => useReady(["triage-estimate"], () => query("triage.estimate", {}));
export const useTriageExisting = () => useCommand(["triage-estimate", "jobs"], (confirm: boolean) => command("triage.existing", { confirm }));

export const useSessionContext = (id: string) => useReady(["session-context", id], () => query("session.context", { id }));
export const useSetContext = () => useCommand(["session-context"], (input: { id: string; context: string[] }) => command("session.setContext", input as SetSessionContext));

export const useToolCatalog = () => useReady(["permissions", "catalog"], () => query("tools.catalog", {}));
export const useUsage = () => useReady(["usage"], () => query("usage.get", {}));
export const useSetCap = () => useCommand(["usage"], (daily_cap: number) => command("usage.setCap", { daily_cap }));
export const useQuietHours = () => useReady(["quiet"], () => query("quietHours.get", {}));
export const useSaveQuietHours = () => useCommand(["quiet"], (input: QuietHours) => command("quietHours.save", input));
export const useSendChecks = () => useReady(["send-checks"], () => query("sendChecks.get", {}));
export const useSaveSendChecks = () => useCommand(["send-checks"], (input: SendCheckSettings) => command("sendChecks.save", input));
export const useGuardRules = () => useReady(["guard"], () => query("guard.rules", {}));
export const useSaveGuardRules = () => useCommand(["guard"], (input: GuardRules) => command("guard.save", input));
export const useTestGuard = () => useMutation({ mutationFn: (input: { rules: GuardRules["rules"]; sample: string }) => command("guard.test", input) });
export const useModelProvider = () => useReady(["model-provider"], () => query("models.provider", {}));
export const useSaveModelProvider = () => useCommand(["model-provider", "models"], (input: SaveModelProvider) => command("models.provider.save", input));
export const useListProviderModels = () => useMutation({ mutationFn: (input: ListProviderModels) => command("models.provider.listModels", input) });

/** Everything agents are waiting on the person for. The sidebar, the chat pill and Today all use it. */
export function useWaitingCount(): number {
  const channel = useChannel();
  const approvals = useApprovals();
  const tasks = useTasks(false);
  const reminders = useReminders();
  const memory = useMemory("");
  const categories = useCategories();
  const suggestions = useSuggestions();
  return (
    (channel.data?.messages ?? []).filter((message) => message.kind === "ask").length +
    (approvals.data?.approvals.length ?? 0) +
    (tasks.data?.tasks ?? []).filter((task) => task.proposed).length +
    (reminders.data?.reminders ?? []).filter((reminder) => reminder.proposed).length +
    (memory.data?.proposals.length ?? 0) +
    (categories.data?.categories ?? []).filter((item) => item.proposed).length +
    (suggestions.data?.suggestions.length ?? 0)
  );
}
