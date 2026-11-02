import type {
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
  GetToolCatalog,
  ListCategories,
  SaveCategory,
  ToolCatalog,
  ActivityList,
  AgentChannelList,
  BoardList,
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
  ListBoard,
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
  RemoveDraft,
  RemoveMailAccount,
  ReplyContext,
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
  UpdateSettings,
} from "./contracts.generated";

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
  "mail.accounts.save": [SaveMailAccount, MailAccounts];
  "mail.accounts.remove": [RemoveMailAccount, MailAccounts];
  "thread.setRead": [SetThreadRead, MailDone];
  "thread.setFlag": [SetThreadFlag, MailDone];
  "thread.move": [MoveThread, MailDone];
  "thread.setStatus": [SetThreadStatus, MailDone];
  "thread.setCategory": [SetThreadCategory, MailDone];
  "rules.save": [RuleSet, RuleSet];
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
  "categories.reorder": [ReorderCategories, CategoryList];
  "categories.decide": [DecideCategory, CategoryList];
  "channel.respond": [RespondChannel, AgentDone];
  "channel.dismiss": [DismissChannel, AgentDone];
  "agentChannel.setMuted": [SetTopicMuted, AgentDone];
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
  "threads.list": [ListThreads, ThreadList];
  "thread.get": [GetThread, ThreadView];
  "rules.get": [GetRules, RuleSet];
  "drafts.list": [ListDrafts, DraftList];
  "mail.replyDraft": [ReplyContext, ReplyDraft];
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
  "cockpit.events": [GetCockpitEvents, CockpitEvents];
  "mailAgent.get": [GetMailAgentSettings, MailAgentSettings];
  "context.get": [GetContextSettings, ContextSettings];
  "session.get": [SessionAction, SessionView];
  "approvals.list": [ListApprovals, ApprovalList];
  "modelCall.get": [GetModelCall, ModelCallView];
  "permissions.get": [GetPermissions, Permissions];
  "tools.catalog": [GetToolCatalog, ToolCatalog];
  "categories.list": [ListCategories, CategoryList];
  "today.view": [GetToday, TodayView];
  "channel.list": [ListChannel, ChannelList];
  "board.list": [ListBoard, BoardList];
  "agentChannel.list": [ListAgentChannel, AgentChannelList];
  "tasks.list": [ListTasks, TaskList];
  "reminders.list": [ListReminders, ReminderList];
  "schedules.list": [ListSchedules, ScheduleList];
  "jobs.list": [ListJobs, JobList];
  "activity.list": [ListActivity, ActivityList];
  "prompts.list": [ListPrompts, PromptList];
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

export async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new ApiRequestError((await response.json()) as ApiError);
  return (await response.json()) as T;
}

export function command<K extends keyof Commands>(name: K, input: Commands[K][0]): Promise<Commands[K][1]> {
  return post(`/api/commands/${name}`, input);
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
