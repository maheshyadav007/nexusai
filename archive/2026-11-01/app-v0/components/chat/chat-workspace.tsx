"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Check,
  Copy,
  Edit3,
  GitBranch,
  MoreHorizontal,
  RefreshCcw,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  WandSparkles
} from "lucide-react";
import { AgentTimeline } from "@/components/chat/agent-timeline";
import { SourceGrid } from "@/components/chat/source-grid";
import { ToolActivityGrid } from "@/components/chat/tool-activity-grid";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ActionTable } from "@/components/work/action-table";
import { EmailCard } from "@/components/work/email-card";
import {
  actionItems,
  agentPlan,
  baseToolRuns,
  importantEmails,
  sources
} from "@/lib/data";
import { useNexusStore } from "@/lib/store";
import type { ToolRun } from "@/lib/types";

const demoQuery = "Summarize my important emails and tell me what needs action today.";

const answerChunks = [
  "I found three important messages that need attention today. ",
  "The highest priority is Maya's supplier risk memo, because the decision is needed before the afternoon review. ",
  "The PLM blocker also needs owner confirmation before the R2 standup, and Elena's renewal thread needs a pricing clarification before the customer prep window. ",
  "I prepared the action list below and drafted two replies for review."
];

function PromptComposer({
  value,
  setValue,
  onSubmit,
  compact,
  disabled
}: {
  value: string;
  setValue: (value: string) => void;
  onSubmit: () => void;
  compact?: boolean;
  disabled?: boolean;
}) {
  return (
    <div className="glass-panel rounded-xl p-sm">
      <div className="flex items-end gap-sm">
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className={compact ? "min-h-3xl" : "min-h-composer"}
          placeholder="Ask NexusAI about your work..."
          disabled={disabled}
        />
        <Button
          aria-label="Send prompt"
          className="mb-xxs shrink-0"
          size="icon"
          variant="primary"
          onClick={onSubmit}
          disabled={disabled || value.trim().length === 0}
        >
          <Send className="size-md" />
        </Button>
      </div>
      <div className="mt-sm flex flex-wrap items-center justify-between gap-sm px-xs">
        <div className="flex flex-wrap gap-xs">
          {["Email", "Calendar", "PLM", "Files"].map((chip) => (
            <Badge key={chip} variant="default">
              {chip}
            </Badge>
          ))}
        </div>
        <span className="text-caption text-ink-tertiary">Personal graph ready</span>
      </div>
    </div>
  );
}

function QueryCard({
  query,
  timestamp,
  onRetry
}: {
  query: string;
  timestamp: string;
  onRetry: () => void;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="surface-panel rounded-xl p-md"
    >
      <div className="mb-sm flex items-center justify-between gap-md">
        <div className="flex items-center gap-xs text-caption text-ink-subtle">
          <GitBranch className="size-sm text-accent" />
          <span>Branch 1/2</span>
          <span>{timestamp}</span>
        </div>
        <div className="flex items-center gap-xxs">
          <Button aria-label="Copy query" size="icon-sm" variant="ghost">
            <Copy className="size-sm" />
          </Button>
          <Button aria-label="Edit query" size="icon-sm" variant="ghost">
            <Edit3 className="size-sm" />
          </Button>
          <Button aria-label="Retry query" size="icon-sm" variant="ghost" onClick={onRetry}>
            <RefreshCcw className="size-sm" />
          </Button>
        </div>
      </div>
      <p className="text-subhead text-ink">{query}</p>
    </motion.section>
  );
}

function AIResponse({
  stream,
  tools,
  currentStep,
  isComplete,
  onRetry
}: {
  stream: string;
  tools: ToolRun[];
  currentStep: number;
  isComplete: boolean;
  onRetry: () => void;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.34, ease: "easeOut" }}
      className="space-y-md"
    >
      <div className="glass-panel rounded-xl p-lg">
        <div className="mb-lg flex items-start justify-between gap-md">
          <div className="flex gap-sm">
            <div className="grid size-2xl place-items-center rounded-lg border border-hairline bg-surface-2">
              <Bot className="size-md text-accent" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-xs">
                <h2 className="text-heading text-ink">NexusAI</h2>
                <Badge variant={isComplete ? "success" : "running"}>
                  {isComplete ? "Complete" : "Streaming"}
                </Badge>
              </div>
              <p className="mt-xxs text-small text-ink-subtle">
                Working across email, calendar, PLM, reminders, and files.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-xxs">
            <Button aria-label="Copy answer" size="icon-sm" variant="ghost">
              <Copy className="size-sm" />
            </Button>
            <Button aria-label="Like answer" size="icon-sm" variant="ghost">
              <ThumbsUp className="size-sm" />
            </Button>
            <Button aria-label="Dislike answer" size="icon-sm" variant="ghost">
              <ThumbsDown className="size-sm" />
            </Button>
            <Button aria-label="Retry answer" size="icon-sm" variant="ghost" onClick={onRetry}>
              <RefreshCcw className="size-sm" />
            </Button>
          </div>
        </div>

        <AgentTimeline steps={agentPlan} currentStep={currentStep} />
        <ToolActivityGrid tools={tools} />

        <div className="rounded-lg border border-hairline bg-surface-1 p-lg">
          <div className="mb-sm flex items-center gap-xs text-caption text-accent">
            <WandSparkles className="size-sm" />
            Final answer
          </div>
          {stream ? (
            <p className="text-body text-ink-muted">
              {stream}
              {!isComplete ? <span className="ml-xxs inline-block h-md w-xxs animate-pulse rounded-full bg-accent" /> : null}
            </p>
          ) : (
            <div className="space-y-xs">
              <div className="h-md w-3/4 animate-pulse rounded-md bg-surface-3" />
              <div className="h-md w-5/6 animate-pulse rounded-md bg-surface-3" />
              <div className="h-md w-2/3 animate-pulse rounded-md bg-surface-3" />
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-md">
        {importantEmails.map((email) => (
          <EmailCard key={email.id} email={email} />
        ))}
      </div>

      <div className="surface-panel rounded-xl p-lg">
        <div className="mb-md flex items-center justify-between gap-md">
          <div>
            <h3 className="text-heading text-ink">Action items for today</h3>
            <p className="mt-xxs text-small text-ink-subtle">Prioritized from cross-workspace context.</p>
          </div>
          <Badge variant="running">4 actions</Badge>
        </div>
        <ActionTable items={actionItems} />
      </div>

      <SourceGrid sources={sources} />

      <div className="surface-panel rounded-xl p-md">
        <div className="mb-sm flex items-center justify-between gap-sm">
          <p className="text-small text-ink">Follow-up suggestions</p>
          <Button aria-label="More follow-up actions" size="icon-sm" variant="ghost">
            <MoreHorizontal className="size-sm" />
          </Button>
        </div>
        <div className="flex flex-wrap gap-xs">
          {[
            "Draft Maya's recommendation reply",
            "Create reminder for PLM owner",
            "Find files tied to renewal pricing",
            "Resolve calendar conflict"
          ].map((suggestion) => (
            <Button key={suggestion} variant="secondary" size="sm">
              <Sparkles className="size-sm" />
              {suggestion}
            </Button>
          ))}
        </div>
      </div>
    </motion.section>
  );
}

export function ChatWorkspace() {
  const [value, setValue] = useState(demoQuery);
  const [query, setQuery] = useState("");
  const [timestamp, setTimestamp] = useState("");
  const [mode, setMode] = useState<"idle" | "running" | "complete">("idle");
  const [stream, setStream] = useState("");
  const [tools, setTools] = useState<ToolRun[]>(baseToolRuns);
  const [currentStep, setCurrentStep] = useState(0);
  const addNotice = useNexusStore((state) => state.addNotice);
  const timers = useRef<number[]>([]);

  const isComplete = mode === "complete";

  const clearTimers = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  };

  const runDemo = () => {
    clearTimers();
    setQuery(value.trim() || demoQuery);
    setTimestamp(
      new Intl.DateTimeFormat("en", {
        hour: "2-digit",
        minute: "2-digit"
      }).format(new Date())
    );
    setMode("running");
    setStream("");
    setCurrentStep(0);
    setTools(baseToolRuns.map((tool) => ({ ...tool, status: "pending" })));

    addNotice({
      title: "Agent run started",
      description: "NexusAI is checking email, calendar, PLM, and reminders.",
      tone: "info"
    });

    baseToolRuns.forEach((tool, index) => {
      timers.current.push(
        window.setTimeout(() => {
          setCurrentStep(Math.min(index + 1, agentPlan.length - 1));
          setTools((previous) =>
            previous.map((item, itemIndex) => {
              if (itemIndex < index) return { ...item, status: "success" };
              if (item.id === tool.id) return { ...item, status: "running" };
              return item;
            })
          );
        }, 420 + index * 780)
      );

      timers.current.push(
        window.setTimeout(() => {
          setTools((previous) =>
            previous.map((item) => (item.id === tool.id ? { ...item, status: "success" } : item))
          );
        }, 900 + index * 780)
      );
    });

    answerChunks.forEach((chunk, index) => {
      timers.current.push(
        window.setTimeout(() => {
          setStream((previous) => `${previous}${chunk}`);
          setCurrentStep(Math.min(agentPlan.length - 1, index + 2));
        }, 3600 + index * 760)
      );
    });

    timers.current.push(
      window.setTimeout(() => {
        setMode("complete");
        setCurrentStep(agentPlan.length - 1);
        addNotice({
          title: "Draft ready",
          description: "Two email replies were prepared for review.",
          tone: "success"
        });
      }, 3600 + answerChunks.length * 760 + 360)
    );
  };

  useEffect(() => () => clearTimers(), []);

  const hasResponse = useMemo(() => mode !== "idle", [mode]);

  return (
    <div className="min-h-screen px-xl py-xl">
      <AnimatePresence mode="wait">
        {!hasResponse ? (
          <motion.section
            key="idle"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -18 }}
            transition={{ duration: 0.32, ease: "easeOut" }}
            className="mx-auto flex min-h-[calc(100vh-var(--space-3xl))] max-w-chat flex-col justify-center"
          >
            <div className="mb-xl">
              <Badge variant="running">
                <Sparkles className="size-sm" />
                NexusAI workspace
              </Badge>
              <h1 className="mt-md text-hero text-balance text-ink">
                Work context, synthesized into action.
              </h1>
              <p className="mt-md max-w-reading text-subhead text-ink-subtle">
                Ask across email, calendar, tasks, reminders, files, PLM issues, and enterprise data.
              </p>
            </div>
            <PromptComposer value={value} setValue={setValue} onSubmit={runDemo} />
          </motion.section>
        ) : (
          <motion.div
            key="response"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mx-auto max-w-chat space-y-md"
          >
            <PromptComposer value={value} setValue={setValue} onSubmit={runDemo} compact disabled={mode === "running"} />
            <QueryCard query={query} timestamp={timestamp} onRetry={runDemo} />
            <AIResponse
              stream={stream}
              tools={tools}
              currentStep={currentStep}
              isComplete={isComplete}
              onRetry={runDemo}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
