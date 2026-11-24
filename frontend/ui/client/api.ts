import type { AgentMap, GetAgentMap, GetRunTree, ListRuns, RunList, RunSpan, SeeAlerts } from "./contracts.generated";
import type { HiddenFromAi, HideFromAi, HideFromAiPreview, HidePreview, UndoHide } from "./contracts.generated";
import type { AddSkill, DecideSkill, ListSkills, SkillList, SkillName } from "./contracts.generated";
import type { CancelTeamTask, CardList, GetTeamTask, ListCards, ListTeamTasks, NoteOnTeamTask, RenameAgent, ResetAgentName, RetryTeamTask, SetMascot, TeamTaskList, TeamTaskView } from "./contracts.generated";
import type { MarkFolderRead } from "./contracts.generated";
import type { GetMailMe, GetNamedYou, MailMe, MePreview, NamedYouList, NotAboutMe, PreviewMe, PreviewRule, RulePreview } from "./contracts.generated";
import type { CategoryRulePreview, ListMixedFolders, MixedFolders, PreviewCategoryRule, SplitFolders } from "./contracts.generated";
import type { AttachToMatter, CloseMatterItems, GetMatter, GetMatterEvents, GetMatterRelated, GetMattersBrief, GetMattersWeek, ListMatters, MatterAction, MatterDetail, MatterDone, MatterEvents, MatterList, MatterRelated, MattersBrief, MattersWeek, MergeMatters, ReopenMatterItems, UnlinkThread } from "./contracts.generated";
import type { MailOrganization, FinishMailLearning, MergeCategories, SortCategory, CategorySortEstimate } from "./contracts.generated";
import type { ApplyMailSort, GetMailSort, MailSort, MailSortApplied, PrepareMailSort, SkipMailSort } from "./contracts.generated";
import type {SimulatePreference, PreferenceSimulation} from "./contracts.generated";
import type {ExpireLearnedNote} from "./contracts.generated";
import type {GetAgentQueue, AgentQueue, QueueAction} from "./contracts.generated";
import type { GetPreferences, PreferenceList, SavePreference, PreferenceHistory, PreferenceVersions, RestorePreference, RecordInteraction, PromptHistory, PromptVersions, RestorePrompt, PreviewPreference, PreferencePreview } from "./contracts.generated";
import type {
  GetGeneration,
  GenerationState,
  AgentRegistry,
  BriefReacted,
  ListAgents,
  ReactToBrief,
  AgentKnowledge,
  ChangeLearnedNote,
  DecideMailSuggestion,
  GetAgentKnowledge,
  ListMailSuggestions,
  MailPreview,
  MailSuggestionList,
  PreviewMail,
  ReadMoreMail,
  SetThreadImportance,
  SetSenderImages,
  DismissChecklist,
  DownloadModel,
  GetSemanticStatus,
  ImportModel,
  ModelName,
  ReadDocumentAgain,
  SaveSemanticSettings,
  SemanticStatus,
  ReorderCategories,
  UpdateCategory,
  DecideApprovals,
  AnswerSession,
  CategoryList,
  CategoryName,
  CategorySaved,
  DecideCategory,
  DecidePriority,
  DraftThreadReply,
  DraftedReply,
  GetToolCatalog,
  ListCategories,
  SaveCategory,
  ToolCatalog,
  ActivityList,
  AgentChannelList,
  ChannelList,
  CheckDraft,
  DecideMemoryProposal,
  DismissChannel,
  GetGuardRules,
  GetModelProvider,
  GetQuietHours,
  GetSendChecks,
  GetThreadRuns,
  GetToday,
  GetUsage,
  GuardRules,
  GuardTestResult,
  JobList,
  ListActivity,
  ListAgentChannel,
  ListChannel,
  ListJobs,
  ListMemory,
  ListPrompts,
  ListProviderModels,
  ListReminders,
  ListSchedules,
  ListTasks,
  MemoryList,
  ModelProviderView,
  PlannerDone,
  PromptList,
  QuietHours,
  ReminderAction,
  ReminderList,
  RemoveMemory,
  RemoveSchedule,
  RespondChannel,
  RunSchedule,
  SaveMemory,
  SaveModelProvider,
  SavePrompt,
  SaveReminder,
  SaveTask,
  Schedule,
  ScheduleList,
  SendCheckResult,
  SendCheckSettings,
  SessionContext,
  SetDailyCap,
  SetDefaults,
  AddConnector,
  GetTriggers,
  ProbeServer,
  RemoveTrigger,
  SaveTrigger,
  ServerProbe,
  TriggerList,
  MarkTodaySeen,
  DocumentReader,
  HomeFolder,
  ListHomeFolder,
  ReadDocument,
  DetectModels,
  ModelDetection,
  RebuildIndex,
  ChooseVersion,
  Connectors,
  ConnectorAction,
  ConnectorTest,
  FindPst,
  GetConnectors,
  GetMailPresets,
  GetPstSearch,
  MailPresets,
  PstSearchStatus,
  PstUploadStarted,
  SetConnectorEnabled,
  StartPstUpload,
  TestConnector,
  Cockpit,
  CockpitEvents,
  GetCockpit,
  GetCockpitEvents,
  CompactResult,
  ContextSettings,
  GetContextSettings,
  GetMailAgentSettings,
  MailAgentRun,
  MailAgentSettings,
  RunMailAgent,
  RateMessage,
  SetSessionContext,
  SetSessionModel,
  SetTopicMuted,
  SnoozeReminder,
  SummarizeThread,
  TaskAction,
  TaskList,
  TestGuardRules,
  ThreadRuns,
  ThreadSummary,
  TodayView,
  TriageEstimate,
  TriageExisting,
  UndoActivity,
  UsageView,
  AgentDone,
  ApprovalList,
  CreateSession,
  DecideApproval,
  GetModelCall,
  GetPermissions,
  ListApprovals,
  ListSessions,
  ModelCallView,
  Permissions,
  RenameSession,
  SessionAction,
  SessionList,
  SessionRow,
  SessionView,
  AddPstImport,
  DocumentDone,
  DocumentLibrary,
  DocumentPreview,
  GetDocument,
  GetPanelBoard,
  GetPanelResults,
  GetPstImports,
  ListDocuments,
  PanelBoard,
  PanelResults,
  PstImportAction,
  PstImports,
  RemoveDocument,
  ResetPanelBoard,
  SaveFolders,
  UpdateDocument,
  Draft,
  DraftList,
  GetMailAccounts,
  GetMailStatus,
  GetRules,
  GetThread,
  ListDrafts,
  ListThreads,
  MailAccounts,
  MailDone,
  MailStatus,
  MailTestResult,
  MoveThread,
  ThreadInInbox,
  ThreadToInbox,
  RemoveDraft,
  RemoveMailAccount,
  ReplyContext,
  ForwardContext,
  SuggestRecipients,
  RecipientSuggestions,
  ReplyDraft,
  RuleSet,
  SaveMailAccount,
  SearchMail,
  SearchResults,
  SendDraft,
  SetThreadCategory,
  SetThreadFlag,
  SetThreadRead,
  SetThreadStatus,
  TestMailAccount,
  ThreadList,
  ThreadView,
  ApiError,
  AvailableModels,
  CancelModelLogin,
  CheckNetwork,
  Diagnostics,
  DisconnectModel,
  EventLog,
  EventLogQuery,
  FinishOnboarding,
  GetDiagnostics,
  GetModelStatus,
  GetOnboarding,
  GetProfile,
  GetSettings,
  GetSidebar,
  GetTrace,
  ListModels,
  ListNotifications,
  LogLines,
  MarkNotificationsRead,
  ModelReply,
  ModelStatus,
  NetworkChecks,
  NotificationList,
  NotificationsChanged,
  OnboardingState,
  Profile,
  ResetSidebar,
  SearchLogs,
  SelectModel,
  SetOnboardingStep,
  Settings,
  SidebarLayout,
  StartModelLogin,
  TestModel,
  TraceView,
  UpdateSettings, ListPipelines, PausePipeline, PipelineList, RunPipeline, StopHistory, GetMoreMail, SetNeverDelete, ChangeThreadFolder, ChangeThreadCategory, PipelineMore, ListMailFolders, MailFolders } from "./contracts.generated";
import { t } from "@/ui/strings";

interface Commands {
  "settings.update": [UpdateSettings, Settings];
  "models.login.start": [StartModelLogin, ModelStatus];
  "models.login.cancel": [CancelModelLogin, ModelStatus];
  "models.disconnect": [DisconnectModel, ModelStatus];
  "models.select": [SelectModel, ModelStatus];
  "models.test": [TestModel, ModelReply];
  "onboarding.setStep": [SetOnboardingStep, OnboardingState];
  "onboarding.finish": [FinishOnboarding, OnboardingState];
  "profile.update": [Profile, Profile];
  "sidebar.update": [SidebarLayout, SidebarLayout];
  "sidebar.reset": [ResetSidebar, SidebarLayout];
  "notifications.markRead": [MarkNotificationsRead, NotificationsChanged];
  "network.check": [CheckNetwork, NetworkChecks];
  "mail.accounts.test": [TestMailAccount, MailTestResult];
  "mail.history.stop": [StopHistory, MailStatus];
  "mail.history.more": [GetMoreMail, MailStatus];
  "mail.sync.neverDelete": [SetNeverDelete, MailStatus];
  "mail.images.sender": [SetSenderImages, MailDone];
  "thread.addToFolder": [ChangeThreadFolder, MailDone];
  "thread.removeFromFolder": [ChangeThreadFolder, MailDone];
  "thread.addCategory": [ChangeThreadCategory, MailDone];
  "thread.removeCategory": [ChangeThreadCategory, MailDone];
  "pipelines.stop": [RunPipeline, PipelineList];
  "pipelines.more": [PipelineMore, PipelineList];
  "pipelines.pause": [PausePipeline, PipelineList];
  "pipelines.run": [RunPipeline, PipelineList];
  "mail.accounts.save": [SaveMailAccount, MailAccounts];
  "mail.accounts.remove": [RemoveMailAccount, MailAccounts];
  "thread.setRead": [SetThreadRead, MailDone];
  "mail.markFolderRead": [MarkFolderRead, MailDone];
  "thread.setFlag": [SetThreadFlag, MailDone];
  "thread.move": [MoveThread, MailDone];
  "thread.toInbox": [ThreadToInbox, ThreadInInbox];
  "mail.hide": [HideFromAi, HiddenFromAi];
  "mail.hide.undo": [UndoHide, MailDone];
  "thread.setStatus": [SetThreadStatus, MailDone];
  "thread.setImportance": [SetThreadImportance, MailDone];
  "thread.setCategory": [SetThreadCategory, MailDone];
  "rules.save": [RuleSet, RuleSet];
  "me.save": [MailMe, MailMe];
  "me.notAboutMe": [NotAboutMe, MailMe];
  "drafts.save": [Draft, Draft];
  "drafts.remove": [RemoveDraft, MailDone];
  "mail.send": [SendDraft, MailDone];
  "documents.update": [UpdateDocument, DocumentDone];
  "documents.saveFolders": [SaveFolders, DocumentDone];
  "documents.remove": [RemoveDocument, DocumentDone];
  "documents.readAgain": [ReadDocumentAgain, DocumentDone];
  "semantic.download": [DownloadModel, SemanticStatus];
  "semantic.cancel": [ModelName, SemanticStatus];
  "semantic.remove": [ModelName, SemanticStatus];
  "semantic.setActive": [ModelName, SemanticStatus];
  "semantic.saveSettings": [SaveSemanticSettings, SemanticStatus];
  "semantic.importFiles": [ImportModel, SemanticStatus];
  "onboarding.dismissChecklist": [DismissChecklist, OnboardingState];
  "pst.add": [AddPstImport, PstImports];
  "pst.pause": [PstImportAction, PstImports];
  "pst.resume": [PstImportAction, PstImports];
  "panels.saveBoard": [PanelBoard, PanelBoard];
  "panels.reset": [ResetPanelBoard, PanelBoard];
  "session.create": [CreateSession, SessionRow];
  "session.stop": [SessionAction, AgentDone];
  "session.rename": [RenameSession, AgentDone];
  "session.archive": [SessionAction, AgentDone];
  "approvals.decide": [DecideApproval, AgentDone];
  "approvals.decideMany": [DecideApprovals, AgentDone];
  "permissions.save": [Permissions, Permissions];
  "session.answer": [AnswerSession, AgentDone];
  "categories.save": [SaveCategory, CategorySaved];
  "categories.remove": [CategoryName, CategoryList];
  "categories.update": [UpdateCategory, CategoryList];
  "categories.merge": [MergeCategories, CategoryList];
  "categories.sort": [SortCategory, CategorySortEstimate];
  "mail.learning.finish": [FinishMailLearning, MailOrganization];
  "mail.sort.prepare": [PrepareMailSort, MailSort];
  "mail.sort.apply": [ApplyMailSort, MailSortApplied];
  "mail.sort.skip": [SkipMailSort, MailSort];
  "categories.reorder": [ReorderCategories, CategoryList];
  "categories.decide": [DecideCategory, CategoryList];
  "categories.decidePriority": [DecidePriority, CategoryList];
  "categories.split": [SplitFolders, CategoryList];
  "thread.draftReply": [DraftThreadReply, DraftedReply];
  "channel.respond": [RespondChannel, AgentDone];
  "channel.dismiss": [DismissChannel, AgentDone];
  "agentChannel.setMuted": [SetTopicMuted, AgentDone];
  "agent.rename": [RenameAgent, CardList];
  "agent.resetName": [ResetAgentName, CardList];
  "agent.setMascot": [SetMascot, CardList];
  "team.note": [NoteOnTeamTask, TeamTaskView];
  "team.cancel": [CancelTeamTask, TeamTaskView];
  "team.retry": [RetryTeamTask, TeamTaskView];
  "skills.add": [AddSkill, SkillList];
  "skills.decide": [DecideSkill, SkillList];
  "skills.reapprove": [SkillName, SkillList];
  "skills.remove": [SkillName, SkillList];
  "monitor.seen": [SeeAlerts, AgentDone];
  "tasks.save": [SaveTask, PlannerDone];
  "tasks.remove": [TaskAction, PlannerDone];
  "reminders.save": [SaveReminder, PlannerDone];
  "reminders.snooze": [SnoozeReminder, PlannerDone];
  "reminders.remove": [ReminderAction, PlannerDone];
  "schedules.save": [Schedule, ScheduleList];
  "schedules.remove": [RemoveSchedule, ScheduleList];
  "schedules.runNow": [RunSchedule, AgentDone];
  "schedules.setDefaults": [SetDefaults, ScheduleList];
  "activity.undo": [UndoActivity, AgentDone];
  "prompts.save": [SavePrompt, AgentDone];
  "agentQueue.act": [QueueAction, AgentDone];
  "memory.expireNote": [ExpireLearnedNote, AgentDone];
  "mailAgent.retryLearning": [GetMailAgentSettings, AgentDone];
  "preferences.simulate": [SimulatePreference, PreferenceSimulation];
  "preferences.save": [SavePreference, PreferenceList];
  "preferences.restore": [RestorePreference, PreferenceList];
  "preferences.preview": [PreviewPreference, PreferencePreview];
  "interactions.record": [RecordInteraction, AgentDone];
  "prompts.restore": [RestorePrompt, AgentDone];
  "prompts.useStarters": [ListPrompts, AgentDone];
  "memory.save": [SaveMemory, AgentDone];
  "memory.remove": [RemoveMemory, AgentDone];
  "memory.decide": [DecideMemoryProposal, AgentDone];
  "thread.summarize": [SummarizeThread, ThreadSummary];
  "triage.existing": [TriageExisting, TriageEstimate];
  "session.setContext": [SetSessionContext, AgentDone];
  "session.setModel": [SetSessionModel, AgentDone];
  "mail.accounts.probe": [ProbeServer, ServerProbe];
  "triggers.save": [SaveTrigger, TriggerList];
  "triggers.remove": [RemoveTrigger, TriggerList];
  "today.markSeen": [MarkTodaySeen, AgentDone];
  "matters.done": [MatterAction, MatterDone];
  "matters.reopen": [MatterAction, AgentDone];
  "matters.unlink": [UnlinkThread, MatterDone];
  "matters.closeItems": [CloseMatterItems, MatterDone];
  "matters.reopenItems": [ReopenMatterItems, MatterDone];
  "matters.merge": [MergeMatters, MatterDone];
  "matters.unmerge": [MatterAction, MatterDone];
  "matters.attach": [AttachToMatter, MatterDone];
  "semantic.rebuild": [RebuildIndex, SemanticStatus];
  "connectors.test": [TestConnector, ConnectorTest];
  "connectors.add": [AddConnector, Connectors];
  "connectors.refresh": [ConnectorAction, Connectors];
  "connectors.approve": [ConnectorAction, Connectors];
  "connectors.remove": [ConnectorAction, Connectors];
  "connectors.setEnabled": [SetConnectorEnabled, Connectors];
  "pst.find": [FindPst, PstSearchStatus];
  "pst.findStop": [GetPstSearch, PstSearchStatus];
  "pst.uploadStart": [StartPstUpload, PstUploadStarted];
  "session.compact": [SessionAction, CompactResult];
  "mailAgent.save": [MailAgentSettings, MailAgentSettings];
  "mailAgent.runNow": [RunMailAgent, MailAgentRun];
  "mailAgent.readMore": [ReadMoreMail, AgentDone];
  "memory.confirmNote": [ChangeLearnedNote, AgentDone];
  "brief.react": [ReactToBrief, BriefReacted];
  "memory.removeNote": [ChangeLearnedNote, AgentDone];
  "suggestions.decide": [DecideMailSuggestion, AgentDone];
  "context.save": [ContextSettings, ContextSettings];
  "session.chooseVersion": [ChooseVersion, SessionView];
  "message.rate": [RateMessage, AgentDone];
  "usage.setCap": [SetDailyCap, UsageView];
  "quietHours.save": [QuietHours, QuietHours];
  "sendChecks.save": [SendCheckSettings, SendCheckSettings];
  "guard.save": [GuardRules, GuardRules];
  "guard.test": [TestGuardRules, GuardTestResult];
  "models.provider.save": [SaveModelProvider, ModelProviderView];
  "models.provider.listModels": [ListProviderModels, AvailableModels];
}

interface Queries {
  "generation.get": [GetGeneration, GenerationState];
  "settings.get": [GetSettings, Settings];
  "models.status": [GetModelStatus, ModelStatus];
  "models.list": [ListModels, AvailableModels];
  "onboarding.state": [GetOnboarding, OnboardingState];
  "profile.get": [GetProfile, Profile];
  "sidebar.get": [GetSidebar, SidebarLayout];
  "notifications.list": [ListNotifications, NotificationList];
  "logs.search": [SearchLogs, LogLines];
  "trace.get": [GetTrace, TraceView];
  "diagnostics.get": [GetDiagnostics, Diagnostics];
  "mail.accounts": [GetMailAccounts, MailAccounts];
  "mail.status": [GetMailStatus, MailStatus];
  "mail.organization": [GetMailStatus, MailOrganization];
  "mail.sort.get": [GetMailSort, MailSort];
  "threads.list": [ListThreads, ThreadList];
  "thread.get": [GetThread, ThreadView];
  "rules.get": [GetRules, RuleSet];
  "rules.preview": [PreviewRule, RulePreview];
  "me.get": [GetMailMe, MailMe];
  "me.named": [GetNamedYou, NamedYouList];
  "me.preview": [PreviewMe, MePreview];
  "mail.hide.preview": [HidePreview, HideFromAiPreview];
  "drafts.list": [ListDrafts, DraftList];
  "mail.replyDraft": [ReplyContext, ReplyDraft];
  "mail.forwardDraft": [ForwardContext, ReplyDraft];
  "mail.suggestRecipients": [SuggestRecipients, RecipientSuggestions];
  "search.run": [SearchMail, SearchResults];
  "semantic.status": [GetSemanticStatus, SemanticStatus];
  "documents.list": [ListDocuments, DocumentLibrary];
  "documents.get": [GetDocument, DocumentPreview];
  "pst.imports": [GetPstImports, PstImports];
  "panels.board": [GetPanelBoard, PanelBoard];
  "panels.results": [GetPanelResults, PanelResults];
  "sessions.list": [ListSessions, SessionList];
  "semantic.detect": [DetectModels, ModelDetection];
  "homeFiles.list": [ListHomeFolder, HomeFolder];
  "documents.read": [ReadDocument, DocumentReader];
  "triggers.list": [GetTriggers, TriggerList];
  "connectors.list": [GetConnectors, Connectors];
  "mail.presets": [GetMailPresets, MailPresets];
  "pst.search": [GetPstSearch, PstSearchStatus];
  "cockpit.view": [GetCockpit, Cockpit];
  "pipelines.list": [ListPipelines, PipelineList];
  "mail.folders": [ListMailFolders, MailFolders];
  "cockpit.events": [GetCockpitEvents, CockpitEvents];
  "mailAgent.get": [GetMailAgentSettings, MailAgentSettings];
  "mailAgent.knowledge": [GetAgentKnowledge, AgentKnowledge];
  "mailAgent.preview": [PreviewMail, MailPreview];
  "suggestions.list": [ListMailSuggestions, MailSuggestionList];
  "context.get": [GetContextSettings, ContextSettings];
  "session.get": [SessionAction, SessionView];
  "approvals.list": [ListApprovals, ApprovalList];
  "modelCall.get": [GetModelCall, ModelCallView];
  "permissions.get": [GetPermissions, Permissions];
  "tools.catalog": [GetToolCatalog, ToolCatalog];
  "categories.list": [ListCategories, CategoryList];
  "categories.preview": [PreviewCategoryRule, CategoryRulePreview];
  "categories.mixed": [ListMixedFolders, MixedFolders];
  "today.view": [GetToday, TodayView];
  "matters.brief": [GetMattersBrief, MattersBrief];
  "matters.week": [GetMattersWeek, MattersWeek];
  "matters.list": [ListMatters, MatterList];
  "matters.get": [GetMatter, MatterDetail];
  "matters.events": [GetMatterEvents, MatterEvents];
  "matters.related": [GetMatterRelated, MatterRelated];
  "channel.list": [ListChannel, ChannelList];
  "agentChannel.list": [ListAgentChannel, AgentChannelList];
  "agents.registry": [ListAgents, AgentRegistry];
  "agents.cards": [ListCards, CardList];
  "team.tasks": [ListTeamTasks, TeamTaskList];
  "team.task": [GetTeamTask, TeamTaskView];
  "skills.list": [ListSkills, SkillList];
  "agents.map": [GetAgentMap, AgentMap];
  "runs.list": [ListRuns, RunList];
  "run.tree": [GetRunTree, RunSpan];
  "tasks.list": [ListTasks, TaskList];
  "reminders.list": [ListReminders, ReminderList];
  "schedules.list": [ListSchedules, ScheduleList];
  "jobs.list": [ListJobs, JobList];
  "activity.list": [ListActivity, ActivityList];
  "prompts.list": [ListPrompts, PromptList];
  "agentQueue.get": [GetAgentQueue, AgentQueue];
  "preferences.list": [GetPreferences, PreferenceList];
  "preferences.history": [PreferenceHistory, PreferenceVersions];
  "prompts.history": [PromptHistory, PromptVersions];
  "memory.list": [ListMemory, MemoryList];
  "thread.summary": [SummarizeThread, ThreadSummary];
  "triage.runs": [GetThreadRuns, ThreadRuns];
  "triage.estimate": [ListJobs, TriageEstimate];
  "session.context": [SessionAction, SessionContext];
  "usage.get": [GetUsage, UsageView];
  "quietHours.get": [GetQuietHours, QuietHours];
  "sendChecks.get": [GetSendChecks, SendCheckSettings];
  "guard.rules": [GetGuardRules, GuardRules];
  "models.provider": [GetModelProvider, ModelProviderView];
  "mail.checkSend": [CheckDraft, SendCheckResult];
}

export class ApiRequestError extends Error {
  constructor(readonly detail: ApiError) {
    super(detail.message);
  }
}

export async function post<T>(path: string, body: unknown, traceId?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(traceId ? { "x-trace-id": traceId } : {}) },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    // The browser hides why, whether the server is down or the address was refused.
    throw new ApiRequestError({ code: "request.unreachable", message: t("error.unreachable") });
  }
  if (!response.ok) {
    const refusal = await response.json().catch(() => null);
    throw new ApiRequestError((refusal as ApiError | null) ?? { code: "request.failed", message: t("error.failed", { status: response.status }) });
  }
  return (await response.json()) as T;
}

export function command<K extends keyof Commands>(name: K, input: Commands[K][0], traceId?: string): Promise<Commands[K][1]> {
  return post(`/api/commands/${name}`, input, traceId);
}

export function query<K extends keyof Queries>(name: K, input: Queries[K][0]): Promise<Queries[K][1]> {
  return post(`/api/queries/${name}`, input);
}

export function eventLog(input: EventLogQuery): Promise<EventLog> {
  return post("/api/events/log", input);
}

export async function latestSeq(): Promise<number> {
  const response = await fetch("/api/health");
  const health = (await response.json()) as { latest_seq: number };
  return health.latest_seq;
}

export const EVENTS_URL = "/api/events";
