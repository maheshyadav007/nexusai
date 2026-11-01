import { Activity, AlarmClock, Archive, Bell, Bot, BrainCircuit, CalendarDays, Check, ChevronDown, ChevronRight, CircleAlert, Clock, FileText, FolderOpen, Inbox, LayoutPanelTop, ListChecks, Loader, Mails, MessagesSquare, PanelLeftClose, PanelLeftOpen, PenLine, ScrollText, Search, Send, Settings, ShieldCheck, Sun, Tags, Terminal, Upload, WifiOff, X } from "lucide-react";

// Features name an icon by what it's for, so one change here updates every use.
export const ICONS = {
  activity: Activity,
  agent: Bot,
  all: FolderOpen,
  approvals: ShieldCheck,
  archive: Archive,
  categories: Tags,
  channel: MessagesSquare,
  check: Check,
  chevronDown: ChevronDown,
  chevronRight: ChevronRight,
  close: X,
  collapse: PanelLeftClose,
  documents: FileText,
  drafts: PenLine,
  error: CircleAlert,
  expand: PanelLeftOpen,
  fromEmail: Mails,
  inbox: Inbox,
  loading: Loader,
  logs: ScrollText,
  memory: BrainCircuit,
  notifications: Bell,
  offline: WifiOff,
  panels: LayoutPanelTop,
  reminders: AlarmClock,
  schedules: CalendarDays,
  search: Search,
  sent: Send,
  sessions: Terminal,
  settings: Settings,
  tasks: ListChecks,
  background: Clock,
  today: Sun,
  uploaded: Upload,
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "h-4 w-4 shrink-0" }: { name: IconName; className?: string }) {
  const Glyph = ICONS[name];
  return <Glyph aria-hidden className={className} />;
}
