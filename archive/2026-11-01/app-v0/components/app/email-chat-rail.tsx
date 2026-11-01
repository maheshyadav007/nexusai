"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  ArrowRight,
  ArrowUpRight,
  BellPlus,
  Bot,
  BrainCircuit,
  Copy,
  GitBranch,
  Loader2,
  MessageSquareText,
  RefreshCcw,
  Send,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UserRound
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { sources } from "@/lib/data";
import { useNexusStore } from "@/lib/store";

const defaultQuestion = "What needs action from my indexed emails today?";

const markdownChunks = [
  "### Action brief\n\n",
  "You have **three email-driven actions** that matter today.\n\n",
  "1. **Maya's supplier risk memo** is the highest priority. Reply before the 2 PM review with a go/no-go recommendation and attach the latest risk delta.\n",
  "2. **PLM-1842** is blocking the R2 release gate. Assign or confirm the thermal validation owner before standup.\n",
  "3. **Elena's renewal thread** needs pricing and retention clarification before the customer prep window.\n\n",
  "**Suggested order:** supplier memo -> PLM owner -> renewal draft."
];

const followUps = [
  "Draft the supplier risk reply",
  "Show only unread priority mail",
  "Create a reminder from this answer",
  "Reclassify similar emails"
];

function MarkdownAnswer({ value }: { value: string }) {
  return (
    <div className="text-small">
      <ReactMarkdown
        components={{
          h3: ({ children }) => <h3 className="mb-sm text-heading text-ink">{children}</h3>,
          p: ({ children }) => <p className="my-xs text-ink-muted">{children}</p>,
          strong: ({ children }) => <strong className="font-medium text-ink">{children}</strong>,
          ol: ({ children }) => <ol className="my-sm list-decimal space-y-xs pl-lg text-ink-muted">{children}</ol>,
          li: ({ children }) => <li className="pl-xxs">{children}</li>
        }}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}

export function EmailChatRail() {
  const [question, setQuestion] = useState(defaultQuestion);
  const [submittedQuestion, setSubmittedQuestion] = useState(defaultQuestion);
  const [answer, setAnswer] = useState("");
  const [running, setRunning] = useState(false);
  const [branch, setBranch] = useState(1);
  const selectedEmailId = useNexusStore((state) => state.selectedEmailId);
  const selectedEmail = useNexusStore((state) =>
    state.emails.find((email) => email.id === state.selectedEmailId)
  );
  const createEntityReminder = useNexusStore((state) => state.createEntityReminder);
  const requestReclassification = useNexusStore((state) => state.requestReclassification);
  const timers = useRef<number[]>([]);

  const clearTimers = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  };

  const createChatReminder = () => {
    createEntityReminder({
      title: "Reminder from NexusAI answer",
      entityTitle: selectedEmail?.subject ?? submittedQuestion,
      entityType: selectedEmail ? "email" : "chat",
      trigger: "chat",
      sourceId: selectedEmailId,
      note: "Created from the assistant rail after summarizing indexed context."
    });
  };

  const reclassifyFromChat = () => {
    if (!selectedEmail) return;
    requestReclassification({
      emailId: selectedEmail.id,
      trigger: "chat",
      reason: "User corrected the classifier from chat after reviewing the answer and sources."
    });
  };

  const handleFollowUp = (followUp: string) => {
    setQuestion(followUp);
    if (followUp === "Create a reminder from this answer") createChatReminder();
    if (followUp === "Reclassify similar emails") reclassifyFromChat();
  };

  const runChat = () => {
    clearTimers();
    setSubmittedQuestion(question.trim() || defaultQuestion);
    setAnswer("");
    setRunning(true);
    setBranch((value) => (value === 3 ? 1 : value + 1));

    markdownChunks.forEach((chunk, index) => {
      timers.current.push(
        window.setTimeout(() => {
          setAnswer((current) => `${current}${chunk}`);
        }, 260 + index * 520)
      );
    });

    timers.current.push(
      window.setTimeout(() => {
        setRunning(false);
      }, 260 + markdownChunks.length * 520 + 220)
    );
  };

  useEffect(() => {
    runChat();
    return () => clearTimers();
  }, []);

  return (
    <aside className="intelligence-panel flex h-[calc(100vh-var(--layout-topbar))] flex-col border-l border-hairline bg-canvas">
      <div className="border-b border-hairline px-md py-sm">
        <div className="flex items-start justify-between gap-sm">
          <div className="flex items-center gap-sm">
            <div className="grid size-2xl place-items-center border border-hairline bg-surface-1">
              <MessageSquareText className="size-md text-accent" />
            </div>
            <div>
              <p className="text-small text-ink">Ask indexed email</p>
              <p className="text-caption text-ink-subtle">Answers with context</p>
            </div>
          </div>
          <Badge variant={running ? "running" : "success"}>
            {running ? <Loader2 className="size-sm animate-spin" /> : <Sparkles className="size-sm" />}
            {running ? "thinking" : "ready"}
          </Badge>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-md overflow-y-auto px-md py-md">
        <section className="ml-auto max-w-[88%] border border-hairline bg-surface-1 p-sm shadow-panel">
          <div className="mb-xs flex items-center justify-between gap-sm">
            <span className="flex items-center gap-xs text-caption text-ink-tertiary">
              <UserRound className="size-sm" />
              You / 09:42
            </span>
            <div className="flex items-center gap-xxs">
              <Button aria-label="Copy question" size="icon-sm" variant="ghost">
                <Copy className="size-sm" />
              </Button>
              <Button aria-label="Retry question" size="icon-sm" variant="ghost" onClick={runChat}>
                <RefreshCcw className="size-sm" />
              </Button>
            </div>
          </div>
          <p className="text-small text-ink">{submittedQuestion}</p>
          <div className="mt-sm flex items-center gap-xs text-caption text-ink-tertiary">
            <GitBranch className="size-sm" />
            Branch {branch}/3
          </div>
        </section>

        <section className="px-xxs py-sm">
          <div className="mb-md flex items-start justify-between gap-sm">
            <div className="flex min-w-0 items-start gap-sm">
              <div className="grid size-2xl shrink-0 place-items-center border border-hairline bg-surface-1">
                <Bot className="size-md text-accent" />
              </div>
              <div className="min-w-0">
                <p className="text-small text-ink">NexusAI</p>
                <p className="text-caption text-ink-subtle">Generated from classified email, calendar, PLM, and issue sources</p>
              </div>
            </div>
            <Badge variant={running ? "running" : "success"}>{running ? "streaming" : "answered"}</Badge>
          </div>

          {answer ? <MarkdownAnswer value={answer} /> : null}

          {!answer ? (
            <div className="space-y-xs">
              <div className="h-md w-4/5 animate-pulse bg-surface-2" />
              <div className="h-md w-full animate-pulse bg-surface-2" />
              <div className="h-md w-2/3 animate-pulse bg-surface-2" />
            </div>
          ) : (
            <>
              <div className="mt-md border-t border-hairline pt-sm">
                <button
                  type="button"
                  className="group flex w-full items-center justify-between gap-sm border border-hairline bg-surface-1 px-sm py-xs text-left transition hover:border-hairline-strong hover:bg-surface-2"
                >
                  <span className="flex min-w-0 items-center gap-xs">
                    <span className="grid size-xl shrink-0 place-items-center bg-accent text-caption text-ink-inverse">
                      {sources.length}+
                    </span>
                    <span className="min-w-0">
                      <span className="block text-small text-ink">{sources.length}+ sources</span>
                      <span className="block truncate text-caption text-ink-tertiary">
                        {sources.slice(0, 3).map((source) => source.title).join(" / ")}
                      </span>
                    </span>
                  </span>
                  <ArrowUpRight className="size-sm shrink-0 text-ink-tertiary transition group-hover:text-ink" />
                </button>
              </div>

              <div className="mt-md flex items-center gap-xxs border-t border-hairline pt-sm">
                <Button aria-label="Copy answer" size="icon-sm" variant="ghost">
                  <Copy className="size-sm" />
                </Button>
                <Button aria-label="Like answer" size="icon-sm" variant="ghost">
                  <ThumbsUp className="size-sm" />
                </Button>
                <Button aria-label="Dislike answer" size="icon-sm" variant="ghost">
                  <ThumbsDown className="size-sm" />
                </Button>
                <Button aria-label="Retry answer" className="ml-auto" size="icon-sm" variant="ghost" onClick={runChat}>
                  <RefreshCcw className="size-sm" />
                </Button>
              </div>
              <div className="mt-sm grid grid-cols-2 gap-xs">
                <Button size="sm" variant="secondary" onClick={createChatReminder}>
                  <BellPlus className="size-sm" />
                  Create reminder
                </Button>
                <Button size="sm" variant="secondary" onClick={reclassifyFromChat} disabled={!selectedEmail}>
                  <BrainCircuit className="size-sm" />
                  Teach classifier
                </Button>
              </div>
            </>
          )}
        </section>

        <section className="border-t border-hairline pt-sm">
          <p className="mb-xs text-caption text-ink-tertiary">Follow up</p>
          {followUps.map((followUp) => (
            <button
              key={followUp}
              type="button"
              onClick={() => handleFollowUp(followUp)}
              className="group flex w-full items-center justify-between gap-sm border-b border-hairline py-sm text-left transition hover:bg-surface-1"
            >
              <span className="text-small text-ink-muted group-hover:text-ink">{followUp}</span>
              <ArrowRight className="size-sm shrink-0 text-ink-tertiary group-hover:text-accent" />
            </button>
          ))}
        </section>
      </div>

      <div className="border-t border-hairline bg-surface-1 p-md">
        <Textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          className="min-h-3xl border-hairline bg-canvas p-sm shadow-none focus-visible:shadow-focus"
          placeholder="Ask about your indexed email..."
        />
        <div className="mt-sm flex items-center justify-between gap-sm">
          <div className="flex items-center gap-xs text-caption text-ink-tertiary">
            <Sparkles className="size-sm text-accent" />
            semantic email index ready
          </div>
          <Button size="sm" variant="primary" onClick={runChat} disabled={running}>
            {running ? <Loader2 className="size-sm animate-spin" /> : <Send className="size-sm" />}
            Send
          </Button>
        </div>
      </div>
    </aside>
  );
}
