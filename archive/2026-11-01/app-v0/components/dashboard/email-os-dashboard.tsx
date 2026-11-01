"use client";

import { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BadgeCheck,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  Clock3,
  GripVertical,
  Inbox,
  Lightbulb,
  MailCheck,
  MessageSquareText,
  Pencil,
  Plus,
  ShieldCheck,
  Sparkles,
  TimerReset,
  Trash2,
  UserRound,
  Workflow,
  Zap
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AnimatedBullet } from "@/components/dashboard/animated-bullet";
import { isPriorityInboxEmail } from "@/lib/email-filters";
import { useNexusStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const attentionLanes = [
  {
    id: "now",
    label: "Now",
    title: "Reply to Maya with the supplier risk recommendation.",
    meta: "Due before 2 PM review / blocks executive decision",
    icon: Zap,
    badge: "critical"
  },
  {
    id: "next",
    label: "Next",
    title: "Confirm PLM-1842 thermal validation owner.",
    meta: "Needed before release standup / owner missing",
    icon: Workflow,
    badge: "high"
  },
  {
    id: "waiting",
    label: "Waiting",
    title: "Finance approval before sending renewal pricing language.",
    meta: "NexusAI will watch for reply and reopen this lane",
    icon: TimerReset,
    badge: "medium"
  },
  {
    id: "ignore",
    label: "Ignore",
    title: "12 FYI messages and status digests are muted until tomorrow.",
    meta: "Low impact, no asks, no decision language",
    icon: ShieldCheck,
    badge: "default"
  }
] as const;

const timeline = [
  { time: "08:41", title: "Maya asks for supplier decision", tone: "critical" },
  { time: "11:00", title: "R2 release standup", tone: "high" },
  { time: "13:30", title: "Reminder: risk reply latest safe send", tone: "critical" },
  { time: "14:00", title: "Supplier risk review", tone: "high" },
  { time: "15:30", title: "Enterprise renewal prep", tone: "medium" }
] as const;

const commitments = [
  {
    owner: "You",
    promise: "Send go/no-go recommendation to Maya",
    due: "1:30 PM",
    source: "Maya Chen thread",
    status: "At risk"
  },
  {
    owner: "Arjun",
    promise: "Name thermal validation owner for PLM-1842",
    due: "11:00 AM",
    source: "PLM release gate",
    status: "Waiting"
  },
  {
    owner: "NexusAI",
    promise: "Prepare Elena renewal reply for review",
    due: "2:45 PM",
    source: "Customer thread",
    status: "Drafting"
  }
];

const personalMemory = [
  {
    title: "Writing style",
    value: "Decision first, short rationale, no long preamble.",
    source: "learned from 14 sent replies"
  },
  {
    title: "Work rhythm",
    value: "Protect deep work before 11 AM unless a customer or release gate is blocked.",
    source: "calendar pattern"
  },
  {
    title: "Escalation rule",
    value: "Ownerless release blockers should become reminders after 2 hours.",
    source: "accepted automation"
  },
  {
    title: "Approval boundary",
    value: "Never send external pricing language without explicit review.",
    source: "workspace policy"
  }
];

const agentQueue = [
  {
    title: "Draft supplier risk reply",
    detail: "Use recommendation-first tone and attach risk delta reference.",
    state: "Ready"
  },
  {
    title: "Create reminder if PLM owner is still missing",
    detail: "Wait until 11:20, then remind Arjun and you.",
    state: "Armed"
  },
  {
    title: "Prepare renewal email",
    detail: "Hold before send until finance approval arrives.",
    state: "Needs review"
  }
];

const modules = ["timeline", "commitments", "memory", "agent"] as const;

function ModuleFrame({
  id,
  title,
  eyebrow,
  icon: Icon,
  editing,
  onHide,
  children,
  className
}: {
  id: (typeof modules)[number];
  title: string;
  eyebrow: string;
  icon: typeof Sparkles;
  editing: boolean;
  onHide: (id: (typeof modules)[number]) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className={className}>
      <Card className="group h-full p-md">
        <div className="mb-md flex items-start justify-between gap-md">
          <div className="flex min-w-0 items-start gap-sm">
            <div className="grid size-2xl shrink-0 place-items-center border border-hairline bg-surface-2">
              <Icon className="size-md text-accent" />
            </div>
            <div className="min-w-0">
              <p className="mb-xxs text-caption uppercase text-accent">{eyebrow}</p>
              <h3 className="truncate text-heading text-ink">{title}</h3>
            </div>
          </div>
          <div className={cn("flex items-center gap-xxs", editing ? "opacity-100" : "opacity-0 group-hover:opacity-100")}>
            {editing ? <GripVertical className="size-md text-ink-tertiary" /> : null}
            {editing ? (
              <Button size="icon-sm" variant="ghost" aria-label={`Hide ${title}`} onClick={() => onHide(id)}>
                <Trash2 className="size-sm" />
              </Button>
            ) : null}
          </div>
        </div>
        {children}
      </Card>
    </motion.div>
  );
}

export function EmailOSDashboard() {
  const [editing, setEditing] = useState(false);
  const [visibleModules, setVisibleModules] = useState<Array<(typeof modules)[number]>>([...modules]);
  const emails = useNexusStore((state) => state.emails);
  const priorityInbox = emails.filter(isPriorityInboxEmail);
  const unreadPriority = priorityInbox.filter((email) => !email.read);

  const restoreModule = () => {
    const hidden = modules.find((module) => !visibleModules.includes(module));
    if (hidden) setVisibleModules((current) => [...current, hidden]);
  };

  const hideModule = (id: (typeof modules)[number]) => {
    setVisibleModules((current) => current.filter((module) => module !== id));
  };

  return (
    <div className="mx-auto max-w-page px-xl py-lg">
      <section className="mb-lg border-b border-hairline pb-lg">
        <div className="grid gap-lg xl:grid-cols-[minmax(0,1fr)_19rem]">
          <div className="min-w-0">
            <p className="mb-xs text-caption uppercase text-ink-tertiary">Home / Operating picture</p>
            <h2 className="editorial-display text-title text-balance text-ink">
              reply, unblock, protect your time.
            </h2>
            <p className="mt-sm max-w-reading text-small text-ink-subtle">
              NexusAI should behave like a chief-of-staff layer: understand your inbox, extract commitments,
              watch timelines, and prepare agent actions before you ask.
            </p>
          </div>

          <div className="border border-hairline bg-surface-1 p-md">
            <div className="mb-sm flex items-center justify-between gap-sm">
              <Badge variant="running">
                <Sparkles className="size-sm" />
                live brief
              </Badge>
              <span className="text-caption text-ink-tertiary">09:42</span>
            </div>
            <p className="text-small text-ink-muted">
              <AnimatedBullet
                text="Maya's supplier thread is the highest leverage reply."
                replacement="Your next best move is the supplier risk reply before the 2 PM review."
                delay={5600}
              />
            </p>
          </div>
        </div>
      </section>

      <section className="mb-md grid gap-md xl:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.65fr)]">
        <Card className="p-md">
          <div className="mb-md flex flex-wrap items-center justify-between gap-md">
            <div>
              <p className="mb-xxs text-caption uppercase text-accent">Attention lanes</p>
              <h3 className="text-heading text-ink">What the OS thinks you should do</h3>
            </div>
            <div className="flex flex-wrap gap-xs">
              <Button variant={editing ? "primary" : "secondary"} size="sm" onClick={() => setEditing((value) => !value)}>
                <Pencil className="size-sm" />
                {editing ? "Done" : "Edit canvas"}
              </Button>
              <Button variant="secondary" size="sm" onClick={restoreModule} disabled={visibleModules.length === modules.length}>
                <Plus className="size-sm" />
                Restore card
              </Button>
            </div>
          </div>

          <div className="grid gap-xs">
            {attentionLanes.map((lane, index) => {
              const Icon = lane.icon;

              return (
                <motion.div
                  key={lane.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.04 }}
                  className="group grid gap-sm border-b border-hairline py-sm md:grid-cols-[6rem_minmax(0,1fr)_auto]"
                >
                  <div className="flex items-center gap-xs text-caption text-ink-tertiary">
                    <Icon className="size-sm text-accent" />
                    {lane.label}
                  </div>
                  <div className="min-w-0">
                    <p className="text-small text-ink">{lane.title}</p>
                    <p className="mt-xxs text-caption text-ink-subtle">{lane.meta}</p>
                  </div>
                  <div className="flex items-center gap-xs">
                    <Badge variant={lane.badge}>{lane.id}</Badge>
                    <ArrowRight className="size-sm text-ink-tertiary transition group-hover:text-accent" />
                  </div>
                </motion.div>
              );
            })}
          </div>
        </Card>

        <Card className="p-md">
          <p className="mb-xxs text-caption uppercase text-accent">Priority focus</p>
          <div className="mb-md grid grid-cols-2 border border-hairline bg-surface-2">
            <div className="border-r border-hairline p-sm">
              <p className="editorial-display text-title text-accent">{priorityInbox.length}</p>
              <p className="text-caption text-ink-subtle">priority inbox</p>
            </div>
            <div className="p-sm">
              <p className="editorial-display text-title text-ink">{unreadPriority.length}</p>
              <p className="text-caption text-ink-subtle">unread now</p>
            </div>
          </div>
          <p className="text-small text-ink-muted">
            The useful view is not all unread mail. It is the intersection of deadline, sender importance,
            current meetings, and promises you made.
          </p>
          <Button asChild className="mt-md w-full justify-between" variant="secondary">
            <Link href="/emails">
              Open classified inbox
              <ArrowRight className="size-sm" />
            </Link>
          </Button>
        </Card>
      </section>

      <section className="grid gap-md xl:grid-cols-2">
        {visibleModules.includes("timeline") ? (
          <ModuleFrame
            id="timeline"
            title="Timeline pressure"
            eyebrow="Day spine"
            icon={CalendarClock}
            editing={editing}
            onHide={hideModule}
          >
            <div className="space-y-xs">
              {timeline.map((item) => (
                <div key={`${item.time}-${item.title}`} className="grid grid-cols-[4rem_minmax(0,1fr)_auto] gap-sm border-b border-hairline py-sm">
                  <span className="text-caption text-ink-tertiary">{item.time}</span>
                  <span className="text-small text-ink-muted">{item.title}</span>
                  <Badge variant={item.tone}>{item.tone}</Badge>
                </div>
              ))}
            </div>
          </ModuleFrame>
        ) : null}

        {visibleModules.includes("commitments") ? (
          <ModuleFrame
            id="commitments"
            title="Commitment ledger"
            eyebrow="Promises extracted"
            icon={BadgeCheck}
            editing={editing}
            onHide={hideModule}
          >
            <div className="space-y-xs">
              {commitments.map((item) => (
                <div key={item.promise} className="border-b border-hairline py-sm">
                  <div className="mb-xxs flex items-center justify-between gap-sm">
                    <p className="text-small text-ink">{item.promise}</p>
                    <Badge variant={item.status === "At risk" ? "critical" : item.status === "Waiting" ? "medium" : "running"}>
                      {item.status}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-xs text-caption text-ink-tertiary">
                    <span>{item.owner}</span>
                    <span>/</span>
                    <span>{item.due}</span>
                    <span>/</span>
                    <span>{item.source}</span>
                  </div>
                </div>
              ))}
            </div>
          </ModuleFrame>
        ) : null}

        {visibleModules.includes("memory") ? (
          <ModuleFrame
            id="memory"
            title="Personal memory"
            eyebrow="What it knows"
            icon={BrainCircuit}
            editing={editing}
            onHide={hideModule}
          >
            <div className="space-y-xs">
              {personalMemory.map((item) => (
                <div key={item.title} className="grid gap-sm border-b border-hairline py-sm md:grid-cols-[8rem_minmax(0,1fr)]">
                  <div className="flex items-center gap-xs text-caption text-accent">
                    <UserRound className="size-sm" />
                    {item.title}
                  </div>
                  <div>
                    <p className="text-small text-ink-muted">{item.value}</p>
                    <p className="mt-xxs text-caption text-ink-tertiary">{item.source}</p>
                  </div>
                </div>
              ))}
            </div>
          </ModuleFrame>
        ) : null}

        {visibleModules.includes("agent") ? (
          <ModuleFrame
            id="agent"
            title="Agent queue"
            eyebrow="Ready to act"
            icon={MessageSquareText}
            editing={editing}
            onHide={hideModule}
          >
            <div className="space-y-xs">
              {agentQueue.map((item) => (
                <div key={item.title} className="border-b border-hairline py-sm">
                  <div className="mb-xs flex items-start justify-between gap-sm">
                    <div>
                      <p className="text-small text-ink">{item.title}</p>
                      <p className="mt-xxs text-caption text-ink-subtle">{item.detail}</p>
                    </div>
                    <Badge variant={item.state === "Ready" ? "success" : item.state === "Armed" ? "running" : "high"}>
                      {item.state}
                    </Badge>
                  </div>
                  <div className="flex gap-xs">
                    <Button size="sm" variant="secondary">
                      <CheckCircle2 className="size-sm" />
                      Approve
                    </Button>
                    <Button size="sm" variant="ghost">
                      <MailCheck className="size-sm" />
                      Inspect
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </ModuleFrame>
        ) : null}
      </section>

      <section className="mt-md border border-hairline bg-surface-1 p-md">
        <div className="flex flex-wrap items-center justify-between gap-md">
          <div className="flex items-start gap-sm">
            <Lightbulb className="mt-xxs size-md text-accent" />
            <div>
              <p className="text-small text-ink">Underrated productivity layer</p>
              <p className="mt-xxs max-w-reading text-caption text-ink-subtle">
                The system should learn what to ignore, when to interrupt, how you write, and which promises matter.
                That makes the chatbot personal instead of merely searchable.
              </p>
            </div>
          </div>
          <Badge variant="default">
            <Clock3 className="size-sm" />
            UI experiment
          </Badge>
        </div>
      </section>
    </div>
  );
}
