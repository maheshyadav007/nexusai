import type { LucideIcon } from "lucide-react";

export type ThemeName = "terminal" | "editorial" | "mintlify" | "linear" | "nexus" | "graphite";

export type ColorMode = "dark" | "light";

export type Priority = "critical" | "high" | "medium" | "low";

export type WorkStatus = "running" | "success" | "failed" | "pending";

export type NavItem = {
  title: string;
  href: string;
  icon: LucideIcon;
};

export type Email = {
  id: string;
  sender: string;
  senderRole: string;
  subject: string;
  summary: string;
  received: string;
  priority: Priority;
  suggestedAction: string;
  source: string;
};

export type EmailCategory = {
  id: string;
  name: string;
  description: string;
  color: "accent" | "success" | "warning" | "danger" | "info";
  count: number;
  unread: number;
  ruleCount: number;
  aiCount: number;
  isCustom?: boolean;
};

export type ClassifiedEmail = Email & {
  categoryId: string;
  read: boolean;
  confidence: number;
  classificationMode: "Rule" | "AI" | "Hybrid";
  ruleMatches: string[];
  keyInfo: string[];
  entities: string[];
  indexedAt: string;
  sentiment: "urgent" | "neutral" | "positive" | "risk";
};

export type PipelineStep = {
  id: string;
  label: string;
  description: string;
  metric: string;
  status: WorkStatus;
};

export type Reminder = {
  id: string;
  title: string;
  dueTime: string;
  countdown: string;
  status: "due" | "upcoming" | "scheduled" | "complete";
  owner: string;
  trigger?: "manual" | "chat" | "email" | "agent";
  entityType?: "email" | "chat" | "issue" | "calendar" | "manual";
  entityTitle?: string;
  sourceId?: string;
  note?: string;
};

export type ReclassificationEvent = {
  id: string;
  emailId: string;
  emailSubject: string;
  fromCategory: string;
  toCategory: string;
  trigger: "manual" | "chat" | "email";
  reason: string;
  status: "queued" | "applied";
  time: string;
};

export type CalendarEvent = {
  id: string;
  title: string;
  time: string;
  attendees: string[];
  location: string;
  status: "confirmed" | "conflict" | "tentative";
};

export type ActionItem = {
  id: string;
  task: string;
  owner: string;
  due: string;
  source: string;
  priority: Priority;
};

export type ToolRun = {
  id: string;
  name: string;
  input: string;
  output: string;
  status: WorkStatus;
  duration: string;
};

export type SourceCard = {
  id: string;
  title: string;
  origin: string;
  snippet: string;
  confidence: string;
};

export type Automation = {
  id: string;
  title: string;
  summary: string;
  impact: string;
};

export type Panel = {
  id: string;
  title: string;
  category: string;
  priority: Priority;
  lastUpdated: string;
  items: string[];
};

export type ToastNotice = {
  id: string;
  title: string;
  description: string;
  tone: "success" | "warning" | "info" | "danger";
  time: string;
};
