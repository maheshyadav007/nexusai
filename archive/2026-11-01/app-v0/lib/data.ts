import {
  Bell,
  CalendarDays,
  CheckSquare,
  Home,
  Inbox,
  LayoutDashboard,
  Search,
  Settings,
  SquareKanban
} from "lucide-react";
import type {
  ActionItem,
  Automation,
  CalendarEvent,
  ClassifiedEmail,
  Email,
  EmailCategory,
  NavItem,
  Panel,
  PipelineStep,
  Reminder,
  SourceCard,
  ToastNotice,
  ToolRun
} from "@/lib/types";

export const navItems: NavItem[] = [
  { title: "Home", href: "/", icon: Home },
  { title: "Inbox", href: "/inbox", icon: Inbox },
  { title: "Tasks", href: "/tasks", icon: CheckSquare },
  { title: "Reminders", href: "/reminders", icon: Bell },
  { title: "Calendar", href: "/calendar", icon: CalendarDays },
  { title: "Panels", href: "/panels", icon: LayoutDashboard },
  { title: "Search", href: "/search", icon: Search },
  { title: "Settings", href: "/settings", icon: Settings }
];

export const importantEmails: Email[] = [
  {
    id: "email-1",
    sender: "Maya Chen",
    senderRole: "VP Product",
    subject: "Decision needed: supplier risk memo before 2 PM",
    summary:
      "Maya needs a go/no-go recommendation on the revised supplier risk memo before the executive review.",
    received: "08:41",
    priority: "critical",
    suggestedAction: "Reply with recommendation and attach the latest risk delta.",
    source: "Gmail / Executive"
  },
  {
    id: "email-2",
    sender: "Arjun Rao",
    senderRole: "Program Lead",
    subject: "PLM-1842 blocker moved to release gate",
    summary:
      "The thermal validation issue is now blocking the R2 release checklist and needs owner confirmation.",
    received: "09:12",
    priority: "high",
    suggestedAction: "Assign validation owner and confirm mitigation by standup.",
    source: "PLM / Issues"
  },
  {
    id: "email-3",
    sender: "Elena Foster",
    senderRole: "Customer Success",
    subject: "Enterprise renewal call: pricing questions",
    summary:
      "Customer asked for a renewal option that includes SSO audit logs and workspace retention changes.",
    received: "09:38",
    priority: "high",
    suggestedAction: "Send pricing clarification and prep notes before the 4 PM call.",
    source: "Outlook / Customers"
  }
];

export const reminders: Reminder[] = [
  {
    id: "rem-1",
    title: "Send supplier risk recommendation",
    dueTime: "Today, 1:30 PM",
    countdown: "3h 12m",
    status: "due",
    owner: "You"
  },
  {
    id: "rem-2",
    title: "Review draft for Elena renewal email",
    dueTime: "Today, 2:45 PM",
    countdown: "4h 27m",
    status: "upcoming",
    owner: "NexusAI"
  },
  {
    id: "rem-3",
    title: "Follow up on PLM-1842 validation owner",
    dueTime: "Today, 5:00 PM",
    countdown: "6h 42m",
    status: "scheduled",
    owner: "You"
  }
];

export const calendarEvents: CalendarEvent[] = [
  {
    id: "cal-1",
    title: "R2 release standup",
    time: "11:00 - 11:30",
    attendees: ["Maya", "Arjun", "Sam"],
    location: "Meet / Release room",
    status: "confirmed"
  },
  {
    id: "cal-2",
    title: "Supplier risk review",
    time: "14:00 - 14:45",
    attendees: ["Finance", "Ops", "Legal"],
    location: "Boardroom 3",
    status: "conflict"
  },
  {
    id: "cal-3",
    title: "Enterprise renewal prep",
    time: "15:30 - 16:00",
    attendees: ["Elena", "Sales Eng"],
    location: "Meet / Customer desk",
    status: "tentative"
  }
];

export const actionItems: ActionItem[] = [
  {
    id: "act-1",
    task: "Approve supplier risk memo or request revised scenario",
    owner: "You",
    due: "1:30 PM",
    source: "Maya email",
    priority: "critical"
  },
  {
    id: "act-2",
    task: "Confirm thermal validation owner for PLM-1842",
    owner: "Arjun",
    due: "11:00 AM",
    source: "PLM issue",
    priority: "high"
  },
  {
    id: "act-3",
    task: "Send renewal pricing clarification to Elena",
    owner: "You",
    due: "3:00 PM",
    source: "Customer email",
    priority: "high"
  },
  {
    id: "act-4",
    task: "Move board review prep docs into shared folder",
    owner: "NexusAI",
    due: "4:30 PM",
    source: "Calendar",
    priority: "medium"
  }
];

export const agentPlan = [
  "Understanding request",
  "Searching emails",
  "Checking calendar",
  "Creating draft",
  "Final answer"
];

export const baseToolRuns: ToolRun[] = [
  {
    id: "tool-1",
    name: "Email Intelligence",
    input: "Filter unread + high-signal senders across Gmail and Outlook.",
    output: "3 important emails found, 2 require direct replies.",
    status: "pending",
    duration: "1.1s"
  },
  {
    id: "tool-2",
    name: "Calendar Context",
    input: "Inspect today's calendar and map email deadlines to events.",
    output: "1 calendar conflict and 3 dependent meetings detected.",
    status: "pending",
    duration: "0.8s"
  },
  {
    id: "tool-3",
    name: "PLM Issue Search",
    input: "Search open release-gate issues referenced by emails.",
    output: "PLM-1842 is blocking R2 validation until owner is confirmed.",
    status: "pending",
    duration: "1.4s"
  },
  {
    id: "tool-4",
    name: "Draft Composer",
    input: "Prepare concise replies for Maya and Elena with required context.",
    output: "2 draft replies ready for review.",
    status: "pending",
    duration: "1.7s"
  }
];

export const sources: SourceCard[] = [
  {
    id: "src-1",
    title: "Maya Chen email thread",
    origin: "Gmail / Executive",
    snippet: "Decision needed before the 2 PM supplier risk review.",
    confidence: "96%"
  },
  {
    id: "src-2",
    title: "PLM-1842 release gate",
    origin: "PLM / Validation",
    snippet: "Thermal validation owner missing from R2 checklist.",
    confidence: "91%"
  },
  {
    id: "src-3",
    title: "Today's calendar",
    origin: "Google Calendar",
    snippet: "Supplier risk review overlaps with renewal preparation.",
    confidence: "88%"
  },
  {
    id: "src-4",
    title: "Elena renewal thread",
    origin: "Outlook / Customers",
    snippet: "Customer asks for SSO audit logs and retention scope.",
    confidence: "93%"
  },
  {
    id: "src-5",
    title: "Priority inbox graph",
    origin: "NexusAI / Index",
    snippet: "Cross-category action map from executive, customer, release, and swarm signals.",
    confidence: "90%"
  }
];

export const automations: Automation[] = [
  {
    id: "auto-1",
    title: "Classify executive email as action-required",
    summary: "Auto-tag messages from VP+ senders when they contain a deadline.",
    impact: "Saves 8 min/day"
  },
  {
    id: "auto-2",
    title: "Generate prep brief before customer calls",
    summary: "Summarize open threads, issues, and files 30 minutes before meetings.",
    impact: "Reduces missed context"
  },
  {
    id: "auto-3",
    title: "Escalate PLM blockers into reminders",
    summary: "Create reminders when release-gate issues remain ownerless.",
    impact: "Prevents stale blockers"
  }
];

export const initialPanels: Panel[] = [
  {
    id: "panel-1",
    title: "Important emails",
    category: "Inbox",
    priority: "critical",
    lastUpdated: "2 min ago",
    items: [
      "Supplier risk memo needs decision",
      "Customer renewal asks for pricing clarification",
      "Ops asks for release gate owner"
    ]
  },
  {
    id: "panel-2",
    title: "Upcoming meetings",
    category: "Calendar",
    priority: "high",
    lastUpdated: "5 min ago",
    items: [
      "R2 release standup at 11:00",
      "Supplier risk review at 14:00",
      "Enterprise renewal prep at 15:30"
    ]
  },
  {
    id: "panel-3",
    title: "PLM issues",
    category: "Enterprise data",
    priority: "critical",
    lastUpdated: "7 min ago",
    items: [
      "PLM-1842 validation owner missing",
      "PLM-1739 BOM revision awaiting review",
      "PLM-1604 closed after QA signoff"
    ]
  },
  {
    id: "panel-4",
    title: "GitHub / swarm issues",
    category: "Engineering",
    priority: "medium",
    lastUpdated: "11 min ago",
    items: [
      "Swarm retry queue has 2 stuck jobs",
      "Agent eval run failed on dataset refresh",
      "PR #482 needs API contract review"
    ]
  },
  {
    id: "panel-5",
    title: "Draft emails",
    category: "Assistant",
    priority: "high",
    lastUpdated: "Now",
    items: [
      "Reply to Maya with recommendation",
      "Send Elena pricing scope",
      "Ask Arjun for validation owner"
    ]
  },
  {
    id: "panel-6",
    title: "Follow-ups",
    category: "Tasks",
    priority: "medium",
    lastUpdated: "14 min ago",
    items: [
      "Finance approval for supplier memo",
      "Legal signoff on retention language",
      "Sam to publish release notes"
    ]
  }
];

export const initialNotices: ToastNotice[] = [
  {
    id: "notice-1",
    title: "Reminder fired",
    description: "Supplier risk recommendation is due this afternoon.",
    tone: "warning",
    time: "Now"
  },
  {
    id: "notice-2",
    title: "Email classified",
    description: "Maya's thread was marked action-required.",
    tone: "info",
    time: "1m"
  },
  {
    id: "notice-3",
    title: "Draft ready",
    description: "Two email drafts are available for review.",
    tone: "success",
    time: "2m"
  },
  {
    id: "notice-4",
    title: "Calendar conflict detected",
    description: "Supplier review overlaps renewal preparation.",
    tone: "danger",
    time: "4m"
  }
];

export const searchResults = [
  {
    id: "res-1",
    icon: SquareKanban,
    title: "PLM-1842 thermal validation owner",
    meta: "Enterprise graph / Issue",
    excerpt: "Release gate is blocked until a validation owner is assigned."
  },
  {
    id: "res-2",
    icon: Inbox,
    title: "Maya Chen: supplier risk memo",
    meta: "Gmail / Executive",
    excerpt: "Requests final recommendation before today's review."
  },
  {
    id: "res-3",
    icon: CalendarDays,
    title: "Supplier risk review",
    meta: "Calendar / Today",
    excerpt: "Meeting is scheduled at 14:00 with Finance, Ops, and Legal."
  }
];

export const emailCategories: EmailCategory[] = [
  {
    id: "all",
    name: "All indexed mail",
    description: "Everything normalized into the personal work graph.",
    color: "accent",
    count: 1284,
    unread: 32,
    ruleCount: 420,
    aiCount: 864
  },
  {
    id: "priority",
    name: "Priority inbox",
    description: "A cross-category view of the messages most likely to matter now.",
    color: "danger",
    count: 52,
    unread: 16,
    ruleCount: 18,
    aiCount: 34
  },
  {
    id: "action",
    name: "Needs action",
    description: "Deadlines, asks, decisions, and owner gaps.",
    color: "danger",
    count: 18,
    unread: 7,
    ruleCount: 6,
    aiCount: 12
  },
  {
    id: "exec",
    name: "Executive signal",
    description: "High-authority messages and strategic context.",
    color: "warning",
    count: 9,
    unread: 3,
    ruleCount: 4,
    aiCount: 5
  },
  {
    id: "customer",
    name: "Customer commitments",
    description: "Renewals, support risk, promises, and commercial asks.",
    color: "success",
    count: 14,
    unread: 4,
    ruleCount: 5,
    aiCount: 9
  },
  {
    id: "release",
    name: "PLM / release blockers",
    description: "Issues, validation gates, BOM changes, and launch risk.",
    color: "info",
    count: 11,
    unread: 2,
    ruleCount: 7,
    aiCount: 4
  },
  {
    id: "engineering",
    name: "GitHub + swarm",
    description: "PRs, agent runs, failures, evals, and code review.",
    color: "accent",
    count: 23,
    unread: 6,
    ruleCount: 11,
    aiCount: 12
  },
  {
    id: "watch",
    name: "Watchlist",
    description: "Custom user category for topics NexusAI should follow.",
    color: "success",
    count: 6,
    unread: 1,
    ruleCount: 2,
    aiCount: 4,
    isCustom: true
  }
];

export const classifiedEmails: ClassifiedEmail[] = [
  {
    ...importantEmails[0],
    categoryId: "action",
    read: false,
    confidence: 97,
    classificationMode: "Hybrid",
    ruleMatches: ["sender:vp-product", "contains:decision needed", "deadline:<6h"],
    keyInfo: [
      "Decision required before supplier risk review",
      "Expected output is a go/no-go recommendation",
      "Attach latest delta to avoid reopening the thread"
    ],
    entities: ["Supplier risk memo", "Finance", "Ops", "Legal"],
    indexedAt: "2 min ago",
    sentiment: "urgent"
  },
  {
    ...importantEmails[1],
    categoryId: "release",
    read: false,
    confidence: 94,
    classificationMode: "AI",
    ruleMatches: ["mentions:PLM-1842", "contains:blocker", "release_gate:true"],
    keyInfo: [
      "Thermal validation has no confirmed owner",
      "R2 release gate is currently blocked",
      "Best next action is owner assignment before standup"
    ],
    entities: ["PLM-1842", "R2", "Thermal validation"],
    indexedAt: "4 min ago",
    sentiment: "risk"
  },
  {
    ...importantEmails[2],
    categoryId: "customer",
    read: true,
    confidence: 92,
    classificationMode: "Hybrid",
    ruleMatches: ["label:customer", "contains:renewal", "topic:pricing"],
    keyInfo: [
      "Customer asks about SSO audit logs",
      "Retention language needs clarification",
      "Draft reply should be reviewed before 3 PM"
    ],
    entities: ["SSO audit logs", "Retention", "Enterprise renewal"],
    indexedAt: "6 min ago",
    sentiment: "neutral"
  },
  {
    id: "email-4",
    sender: "GitHub",
    senderRole: "Code review",
    subject: "PR #482: API contract review requested",
    summary:
      "The agent orchestration PR is waiting on API contract approval and has one failing eval snapshot.",
    received: "10:04",
    priority: "medium",
    suggestedAction: "Review contract diff and rerun the eval snapshot after changes.",
    source: "GitHub / Pull requests",
    categoryId: "engineering",
    read: false,
    confidence: 89,
    classificationMode: "Rule",
    ruleMatches: ["from:github", "mentions:PR", "review_requested:true"],
    keyInfo: [
      "API contract review is blocking merge",
      "One eval snapshot failed after orchestration change",
      "Review owner is currently you"
    ],
    entities: ["PR #482", "agent orchestration", "API contract"],
    indexedAt: "8 min ago",
    sentiment: "neutral"
  },
  {
    id: "email-5",
    sender: "Swarm Monitor",
    senderRole: "Agent runtime",
    subject: "Two swarm jobs stuck in retry queue",
    summary:
      "The daily research swarm has two jobs looping on stale credentials and one job waiting on vector index refresh.",
    received: "10:16",
    priority: "high",
    suggestedAction: "Rotate token, flush retry queue, and rerun the two blocked jobs.",
    source: "Swarm / Runtime",
    categoryId: "engineering",
    read: false,
    confidence: 95,
    classificationMode: "AI",
    ruleMatches: ["service:swarm", "status:retrying", "severity:high"],
    keyInfo: [
      "Two research agents are stuck in retry",
      "Credential refresh likely resolves one failure class",
      "Vector index refresh is delaying the second job"
    ],
    entities: ["Research swarm", "Retry queue", "Vector index"],
    indexedAt: "Now",
    sentiment: "risk"
  }
];

export const pipelineSteps: PipelineStep[] = [
  {
    id: "emails",
    label: "Email fetching",
    description: "Syncing Gmail, Outlook, issues, and alerts.",
    metric: "1,284 indexed",
    status: "success"
  },
  {
    id: "classification",
    label: "Classification",
    description: "Rule engine + AI router assigning work categories.",
    metric: "96% confidence",
    status: "running"
  },
  {
    id: "indexing",
    label: "Indexing",
    description: "Embedding summaries into your personal work graph.",
    metric: "42 vectors/min",
    status: "running"
  }
];

export const classificationRules = [
  {
    id: "rule-1",
    name: "Executive deadlines",
    pattern: "VP+ sender + deadline language",
    route: "Needs action",
    accuracy: "98.2%"
  },
  {
    id: "rule-2",
    name: "Release blockers",
    pattern: "PLM ID + blocker/release gate terms",
    route: "PLM / release blockers",
    accuracy: "94.7%"
  },
  {
    id: "rule-3",
    name: "Swarm runtime failures",
    pattern: "retry queue, eval failed, stale token",
    route: "GitHub + swarm",
    accuracy: "91.4%"
  }
];

export const indexingConnectors = [
  ["Gmail", "Healthy", "18s ago"],
  ["Outlook", "Healthy", "22s ago"],
  ["Calendar", "Healthy", "31s ago"],
  ["PLM", "Lagging", "2m ago"],
  ["GitHub", "Healthy", "44s ago"],
  ["Swarm", "Attention", "Now"]
];

export const osMetrics = [
  { label: "Classified today", value: "218", detail: "34 action-bearing" },
  { label: "AI confidence", value: "96%", detail: "hybrid classifier" },
  { label: "Index freshness", value: "31s", detail: "median connector lag" },
  { label: "Drafts prepared", value: "6", detail: "2 need review" }
];
