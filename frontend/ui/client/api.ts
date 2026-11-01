import type {
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
