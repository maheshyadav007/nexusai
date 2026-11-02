"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { ToolApproval } from "@/ui/client/contracts.generated";
import { useDateTime } from "@/ui/client/format";
import { useDecideApproval, useDecideApprovals } from "@/ui/client/sessions";
import { Icon, type IconName } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Rise } from "@/ui/primitives/Motion";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { t, tn } from "@/ui/strings";
import { isFinished, toolName, type ToolPart } from "./parts";

function Shell({ children, testid }: { children: ReactNode; testid?: string }) {
  return (
    <Rise as="section" data-testid={testid} className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
      {children}
    </Rise>
  );
}

/**
 * One question, single or multiple choice, always with room to say something else. A single
 * choice answers as soon as it's picked; several wait for Continue. Based on Beautiful UI's
 * Approval Card (MIT).
 */
export function QuestionCard({ question, options, multiple, onAnswer, onSkip, pending, error }: { question: string; options: readonly string[]; multiple: boolean; onAnswer: (answer: string) => void; onSkip?: () => void; pending?: boolean; error?: string | null }) {
  const [picked, setPicked] = useState<readonly string[]>([]);
  const [other, setOther] = useState("");
  const choose = (option: string) => {
    if (!multiple) {
      setPicked([option]);
      onAnswer(option);
      return;
    }
    setPicked((current) => (current.includes(option) ? current.filter((item) => item !== option) : [...current, option]));
  };
  const answer = [...picked, ...(other.trim() ? [other.trim()] : [])].join(", ");
  return (
    <Shell testid="question-card">
      <p className="text-md font-medium text-ink-primary">{question}</p>
      <form
        className="flex flex-col gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          if (answer) onAnswer(answer);
        }}
      >
        {options.length ? (
          <div role={multiple ? "group" : "radiogroup"} aria-label={question} className="flex flex-col gap-px">
            {options.map((option) => {
              const on = picked.includes(option);
              return (
                <Pressable key={option} type="button" role={multiple ? "checkbox" : "radio"} aria-checked={on} disabled={pending} onClick={() => choose(option)} className="focus-ring flex w-full items-center gap-2 rounded-md p-2 text-left text-md text-ink-primary transition-colors duration-fast hover:bg-surface-sunken disabled:opacity-60">
                  <span className={`flex h-4 w-4 shrink-0 items-center justify-center border transition-colors duration-fast ${multiple ? "rounded-sm" : "rounded-full"} ${on ? "border-accent-default bg-accent-default text-accent-on" : "border-line-strong"}`}>{on ? <Icon name="check" className="h-3 w-3" /> : null}</span>
                  {option}
                </Pressable>
              );
            })}
          </div>
        ) : null}
        <BareInput
          aria-label={t(options.length ? "chat.question.other" : "chat.question.answer")}
          placeholder={t(options.length ? "chat.question.other" : "chat.question.answer")}
          value={other}
          disabled={pending}
          onChange={(event) => setOther(event.target.value)}
          className="focus-ring mt-1 w-full rounded-md border border-line-subtle bg-surface-page p-2 text-md text-ink-primary transition-colors duration-fast placeholder:text-ink-muted focus:border-line-strong"
        />
        {error ? <p role="alert" className="text-sm text-status-danger">{error}</p> : null}
        <div className="mt-2 flex items-center justify-end gap-2">
          {onSkip ? (
            <Button variant="quiet" disabled={pending} onClick={onSkip}>
              {t("channel.skip")}
            </Button>
          ) : null}
          <Button type="submit" variant="primary" loading={pending ?? false} disabled={!answer}>
            {t("chat.question.continue")}
          </Button>
        </div>
      </form>
    </Shell>
  );
}

/** A question that's been answered: what was asked, and what the person said. */
export function AnsweredQuestion({ question, answer }: { question: string; answer: string | null }) {
  return (
    <div data-testid="answered-question" className="flex flex-col gap-1 text-md">
      <p className="text-ink-muted">{question}</p>
      <p className="flex items-center gap-2 text-ink-primary">
        <Icon name="check" className="h-3 w-3 text-status-success" />
        {answer ?? t("chat.question.skipped")}
      </p>
    </div>
  );
}

function Decisions({ approval, allow, deny }: { approval: ToolApproval; allow: string; deny: string }) {
  const decide = useDecideApproval();
  const refused = decide.error instanceof ApiRequestError ? decide.error.detail.message : null;
  return (
    <>
      {refused ? <p role="alert" className="text-sm text-status-danger">{refused}</p> : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="quiet" disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "deny" })}>
          {deny}
        </Button>
        {approval.can_remember ? (
          <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "session" })}>
            {t("approvals.session")}
          </Button>
        ) : null}
        <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ id: approval.id, choice: "once" })}>
          {allow}
        </Button>
      </div>
    </>
  );
}

/** The agent wants to do something that needs a yes. */
export function ApprovalCard({ approval }: { approval: ToolApproval }) {
  return (
    <Shell testid="approval">
      <div className="flex flex-col gap-1">
        <p className="break-words text-md font-medium text-ink-primary">{approval.summary}</p>
        <p className="text-sm text-ink-muted">{approval.reason}</p>
      </div>
      {approval.detail ? <pre className="max-h-popover overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-sunken p-2 font-mono text-sm text-ink-secondary">{approval.detail}</pre> : null}
      <Decisions approval={approval} allow={t("approvals.once")} deny={t("approvals.deny")} />
    </Shell>
  );
}

/** Many requests to use one tool, as one decision. Untick any that shouldn't happen. */
export function ApprovalGroupCard({ approvals }: { approvals: readonly ToolApproval[] }) {
  const decide = useDecideApprovals();
  const [left, setLeft] = useState<ReadonlySet<number>>(new Set());
  const first = approvals[0];
  if (!first) return null;
  if (approvals.length === 1) return <ApprovalCard approval={first} />;
  const allowed = approvals.filter((item) => !left.has(item.id)).map((item) => item.id);
  const declined = approvals.filter((item) => left.has(item.id)).map((item) => item.id);
  const refused = decide.error instanceof ApiRequestError ? decide.error.detail.message : null;
  return (
    <Shell testid="approval-group">
      <div className="flex flex-col gap-1">
        <p className="text-md font-medium text-ink-primary">{tn("approvals.group", approvals.length, { label: first.tool_label ?? first.tool })}</p>
        <p className="text-sm text-ink-muted">{first.reason}</p>
      </div>
      <ul aria-label={first.tool_label ?? first.tool} className="flex max-h-popover flex-col gap-1 overflow-y-auto rounded-md bg-surface-sunken p-2">
        {approvals.map((item) => (
          <li key={item.id}>
            <Checkbox
              label={item.summary}
              checked={!left.has(item.id)}
              onChange={(on) =>
                setLeft((current) => {
                  const next = new Set(current);
                  if (on) next.delete(item.id);
                  else next.add(item.id);
                  return next;
                })
              }
            />
          </li>
        ))}
      </ul>
      {refused ? <p role="alert" className="text-sm text-status-danger">{refused}</p> : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="quiet" disabled={decide.isPending} onClick={() => decide.mutate({ deny: approvals.map((item) => item.id) })}>
          {t("approvals.denyAll")}
        </Button>
        {first.can_remember ? (
          <Button disabled={decide.isPending || !allowed.length} onClick={() => decide.mutate({ allow: allowed, deny: declined, remember: true })}>
            {t("approvals.session")}
          </Button>
        ) : null}
        <Button variant="primary" loading={decide.isPending} disabled={!allowed.length} onClick={() => decide.mutate({ allow: allowed, deny: declined })}>
          {t("approvals.allowCount", { count: allowed.length })}
        </Button>
      </div>
    </Shell>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-md">
      <dt className="w-7 shrink-0 text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink-primary">{value}</dd>
    </div>
  );
}

/** A mail about to go, or that went: it reads like a mail, because that's what's being decided. */
export function MailCard({ part, approval }: { part: ToolPart; approval?: ToolApproval | undefined }) {
  const input = part.input ?? {};
  const to = Array.isArray(input.to) ? input.to.join(", ") : "";
  const cc = Array.isArray(input.cc) ? input.cc.join(", ") : "";
  const sent = part.state === "output-available" && part.output === "Sent.";
  const stopped = part.state === "output-denied" || (part.state === "output-available" && !sent);
  return (
    <Shell testid="mail-card">
      <dl className="flex flex-col gap-1 border-b border-line-subtle pb-2">
        <Field label={t("mail.to")} value={to} />
        {cc ? <Field label={t("mail.cc")} value={cc} /> : null}
        <Field label={t("mail.subject")} value={String(input.subject ?? "")} />
      </dl>
      <p className="max-h-popover overflow-y-auto whitespace-pre-wrap break-words text-md text-ink-primary">{String(input.body ?? "")}</p>
      {approval ? <Decisions approval={approval} allow={t("chat.mail.send")} deny={t("chat.mail.dontSend")} /> : null}
      {sent ? (
        <p className="flex items-center gap-2 text-sm text-status-success">
          <Icon name="check" className="h-3 w-3" />
          {t("chat.mail.sent")}
        </p>
      ) : null}
      {stopped ? <p className="text-sm text-ink-muted">{part.state === "output-denied" ? t("chat.mail.notSent") : String(part.output)}</p> : null}
    </Shell>
  );
}

/** What the Mail agent decided about a conversation, and why. */
export function TriageCard({ part, thread }: { part: ToolPart; thread: number | null | undefined }) {
  const input = part.input ?? {};
  const category = typeof input.category === "string" ? input.category : null;
  const importance = String(input.importance ?? "normal");
  return (
    <Shell testid="triage-card">
      <p className="flex flex-wrap items-center gap-2 text-md font-medium text-ink-primary">
        {category ?? t("chat.triage.noCategory")}
        {importance === "high" ? <span className="text-sm font-normal text-accent-default">{t("today.important")}</span> : null}
      </p>
      {input.summary ? <p className="break-words text-md text-ink-primary">{String(input.summary)}</p> : null}
      {input.reason ? <p className="break-words text-sm text-ink-muted">{String(input.reason)}</p> : null}
      {!isFinished(part) ? <p className="text-sm text-ink-muted">{t("chat.result.working")}</p> : null}
      {thread ? (
        <Link href={`/mail/thread/${thread}`} className="focus-ring self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 transition-colors duration-fast hover:text-ink-primary">
          {t("chat.result.openMail")}
        </Link>
      ) : null}
    </Shell>
  );
}

const RESULT: Readonly<Record<string, { icon: IconName; href: string; open: Parameters<typeof t>[0] }>> = {
  create_tasks: { icon: "tasks", href: "/planner/tasks", open: "chat.result.openTasks" },
  propose_task: { icon: "tasks", href: "/planner/tasks", open: "chat.result.openTasks" },
  create_reminders: { icon: "reminders", href: "/planner/reminders", open: "chat.result.openReminders" },
  propose_reminder: { icon: "reminders", href: "/planner/reminders", open: "chat.result.openReminders" },
  create_categories: { icon: "categories", href: "/settings?section=categories", open: "chat.result.openCategories" },
  create_agent: { icon: "schedules", href: "/agent/schedules", open: "chat.result.openAgents" },
  draft_reply: { icon: "drafts", href: "/mail/drafts", open: "chat.result.openDrafts" },
  save_draft: { icon: "drafts", href: "/mail/drafts", open: "chat.result.openDrafts" },
};

/** Tools take a list or one item. Either way it's shown as the things that were made. */
function itemsOf(part: ToolPart): Record<string, unknown>[] {
  const input = part.input ?? {};
  const list = input.tasks ?? input.reminders ?? input.categories;
  return Array.isArray(list) ? (list as Record<string, unknown>[]) : [input];
}

/** What the agent made for the person, and where to find it. The same kind shares one card. */
export function ResultCard({ parts }: { parts: readonly ToolPart[] }) {
  const format = useDateTime();
  const seen = new Set<string>();
  const rows = parts.flatMap((part) =>
    itemsOf(part).flatMap((input, index) => {
      const name = toolName(part);
      const title = String(input.title ?? input.name ?? input.subject ?? t(`tool.${name}` as Parameters<typeof t>[0]));
      if (seen.has(title)) return [];
      seen.add(title);
      return [{ key: `${part.toolCallId}-${index}`, part, name, title, when: typeof input.when === "string" ? format(input.when) : typeof input.due === "string" ? input.due : null }];
    }),
  );
  const shown = RESULT[toolName(parts[0] as ToolPart)];
  const everyDone = parts.every(isFinished);
  return (
    <Shell testid="result-card">
      {rows.map(({ key, part, name, title, when }) => {
        const refused = part.state === "output-denied" || (typeof part.output === "string" && part.output.startsWith("Not allowed"));
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-sunken text-ink-secondary">
              <Icon name={RESULT[name]?.icon ?? "check"} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-md font-medium text-ink-primary">{title}</p>
              <p className="text-sm tabular-nums text-ink-muted">{refused ? t("chat.result.notDone") : !isFinished(part) ? t("chat.result.working") : name.startsWith("propose_") ? t("chat.result.proposed") : when ?? t("chat.result.done")}</p>
            </div>
          </div>
        );
      })}
      {shown && everyDone ? (
        <Link href={shown.href} className="focus-ring self-start rounded-sm text-sm text-ink-secondary underline underline-offset-2 transition-colors duration-fast hover:text-ink-primary">
          {t(shown.open)}
        </Link>
      ) : null}
    </Shell>
  );
}
