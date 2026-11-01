"use client";

import {
  BellPlus,
  BrainCircuit,
  CheckCheck,
  Clock3,
  Inbox,
  MailOpen,
  Radio,
  Search,
  SlidersHorizontal,
  Sparkles,
  Tag
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PriorityBadge } from "@/components/work/priority-badge";
import { getEmailsForCategory, isPriorityInboxEmail } from "@/lib/email-filters";
import { useNexusStore } from "@/lib/store";
import type { ClassifiedEmail } from "@/lib/types";
import { cn } from "@/lib/utils";

function InboxEmailCard({
  email,
  selected,
  onSelect,
  onToggleRead,
  onCreateReminder,
  onReclassify
}: {
  email: ClassifiedEmail;
  selected: boolean;
  onSelect: () => void;
  onToggleRead: () => void;
  onCreateReminder: () => void;
  onReclassify: () => void;
}) {
  return (
    <article
      className={cn(
        "border border-hairline bg-surface-1 transition duration-200 hover:border-hairline-strong hover:bg-surface-2",
        selected && "border-accent shadow-focus",
        !email.read && "bg-surface-1"
      )}
    >
      <button type="button" onClick={onSelect} className="w-full p-md text-left">
        <div className="grid gap-md xl:grid-cols-[minmax(10rem,0.28fr)_minmax(0,1fr)_auto]">
          <div className="flex min-w-0 items-start gap-sm">
            <span className={cn("mt-sm size-xs shrink-0 rounded-full", email.read ? "bg-hairline" : "bg-accent")} />
            <div className="min-w-0">
              <p className={cn("truncate text-small", email.read ? "text-ink-muted" : "font-medium text-ink")}>
                {email.sender}
              </p>
              <p className="mt-xxs truncate text-caption text-ink-tertiary">{email.senderRole}</p>
            </div>
          </div>

          <div className="min-w-0">
            <div className="mb-xs flex min-w-0 flex-wrap items-center gap-xs">
              <h3 className={cn("truncate text-small", email.read ? "text-ink-muted" : "font-medium text-ink")}>
                {email.subject}
              </h3>
              <PriorityBadge priority={email.priority} />
              <Badge variant={email.read ? "default" : "running"}>{email.read ? "read" : "unread"}</Badge>
            </div>
            <p className="line-clamp-2 text-small text-ink-subtle">{email.summary}</p>

            <div className="mt-sm grid gap-xs md:grid-cols-3">
              {email.keyInfo.map((item) => (
                <div key={item} className="border-l border-hairline pl-sm">
                  <p className="line-clamp-2 text-caption text-ink-muted">{item}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="flex shrink-0 flex-col items-start gap-xs xl:items-end">
            <span className="text-caption text-ink-tertiary">{email.received}</span>
            <span className="inline-flex items-center gap-xxs text-caption text-ink-tertiary">
              <Clock3 className="size-sm" />
              {email.indexedAt}
            </span>
          </div>
        </div>

        <div className="mt-md flex flex-wrap items-center gap-xs border-t border-hairline pt-sm">
          <Badge variant="default">
            <Inbox className="size-sm" />
            {email.source}
          </Badge>
          <Badge variant="default">
            <Sparkles className="size-sm" />
            {email.classificationMode}
          </Badge>
          {email.entities.slice(0, 3).map((entity) => (
            <Badge key={entity} variant="default">
              <Tag className="size-sm" />
              {entity}
            </Badge>
          ))}
        </div>
      </button>

      <div className="flex flex-wrap gap-xs border-t border-hairline px-md py-sm">
        <Button size="sm" variant="secondary" onClick={onSelect}>
          <MailOpen className="size-sm" />
          Open
        </Button>
        <Button size="sm" variant="ghost" onClick={onToggleRead}>
          {email.read ? <Radio className="size-sm" /> : <CheckCheck className="size-sm" />}
          {email.read ? "Mark unread" : "Mark read"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCreateReminder}>
          <BellPlus className="size-sm" />
          Remind me
        </Button>
        <Button size="sm" variant="ghost" onClick={onReclassify}>
          <BrainCircuit className="size-sm" />
          Reclassify similar
        </Button>
        <Button size="sm" variant="ghost">
          <Sparkles className="size-sm" />
          Draft reply
        </Button>
      </div>
    </article>
  );
}

export function EmailInboxView() {
  const categories = useNexusStore((state) => state.categories);
  const emails = useNexusStore((state) => state.emails);
  const selectedCategoryId = useNexusStore((state) => state.selectedCategoryId);
  const selectedEmailId = useNexusStore((state) => state.selectedEmailId);
  const selectEmail = useNexusStore((state) => state.selectEmail);
  const toggleEmailRead = useNexusStore((state) => state.toggleEmailRead);
  const createEntityReminder = useNexusStore((state) => state.createEntityReminder);
  const requestReclassification = useNexusStore((state) => state.requestReclassification);
  const reclassificationEvents = useNexusStore((state) => state.reclassificationEvents);

  const selectedCategory = categories.find((category) => category.id === selectedCategoryId) ?? categories[0];
  const visibleEmails = getEmailsForCategory(emails, selectedCategory.id);
  const priorityCount = emails.filter(isPriorityInboxEmail).length;
  const unreadCount = visibleEmails.filter((email) => !email.read).length;

  return (
    <div className="mx-auto max-w-page px-xl py-lg">
      <section className="mb-lg border-b border-hairline pb-lg">
        <div className="flex flex-wrap items-end justify-between gap-lg">
          <div className="max-w-reading">
            <p className="mb-xs text-caption uppercase text-ink-tertiary">Emails / Classified inbox</p>
            <h2 className="editorial-display text-title text-balance text-ink">{selectedCategory.name}</h2>
            <p className="mt-xs text-small text-ink-subtle">{selectedCategory.description}</p>
          </div>

          <div className="grid grid-cols-3 border border-hairline bg-surface-1">
            <div className="border-r border-hairline p-sm text-right">
              <p className="editorial-display text-heading text-accent">{priorityCount}</p>
              <p className="text-caption text-ink-subtle">priority inbox</p>
            </div>
            <div className="border-r border-hairline p-sm text-right">
              <p className="editorial-display text-heading text-ink">{visibleEmails.length}</p>
              <p className="text-caption text-ink-subtle">shown</p>
            </div>
            <div className="p-sm text-right">
              <p className="editorial-display text-heading text-ink">{unreadCount}</p>
              <p className="text-caption text-ink-subtle">unread</p>
            </div>
          </div>
        </div>
      </section>

      <div className="mb-md flex flex-wrap items-center justify-between gap-sm border border-hairline bg-surface-1 p-sm">
        <div className="flex min-w-[18rem] flex-1 items-center gap-xs border border-hairline bg-canvas px-sm">
          <Search className="size-sm text-ink-tertiary" />
          <Input
            aria-label="Search emails"
            placeholder="Search classified email..."
            className="h-xl border-none bg-transparent px-0 text-small shadow-none focus-visible:shadow-none"
          />
        </div>
        <div className="flex gap-xs">
          <Button variant="secondary" size="sm">
            <SlidersHorizontal className="size-sm" />
            Filters
          </Button>
          <Button variant="secondary" size="sm">
            <Sparkles className="size-sm" />
            Explain routing
          </Button>
        </div>
      </div>

      <div className="mb-md grid gap-md xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="border border-hairline bg-surface-1 p-md">
          <div className="mb-sm flex items-center justify-between gap-sm">
            <div>
              <p className="text-caption uppercase text-accent">Feedback loop</p>
              <h3 className="text-heading text-ink">Classifier learns from corrections</h3>
            </div>
            <Badge variant="running">
              <BrainCircuit className="size-sm" />
              active
            </Badge>
          </div>
          <p className="max-w-reading text-small text-ink-subtle">
            When you mark a message as the wrong type, NexusAI can re-evaluate similar emails from the same sender,
            topic, and entity pattern. This can also be triggered from chat.
          </p>
        </div>
        <div className="border border-hairline bg-surface-1 p-md">
          <p className="mb-xs text-caption uppercase text-accent">Recent corrections</p>
          <div className="space-y-xs">
            {reclassificationEvents.slice(0, 2).map((event) => (
              <div key={event.id} className="border-b border-hairline py-xs">
                <p className="line-clamp-1 text-small text-ink">{event.emailSubject}</p>
                <p className="mt-xxs text-caption text-ink-subtle">
                  {event.fromCategory} to {event.toCategory} / {event.trigger}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-sm">
        {visibleEmails.length > 0 ? (
          visibleEmails.map((email) => (
            <InboxEmailCard
              key={email.id}
              email={email}
              selected={selectedEmailId === email.id}
              onSelect={() => selectEmail(email.id)}
              onToggleRead={() => toggleEmailRead(email.id)}
              onCreateReminder={() =>
                createEntityReminder({
                  title: `Follow up: ${email.subject}`,
                  entityTitle: email.subject,
                  entityType: "email",
                  trigger: "email",
                  sourceId: email.id,
                  note: `Linked to ${email.sender} and ${email.source}.`
                })
              }
              onReclassify={() =>
                requestReclassification({
                  emailId: email.id,
                  trigger: "email",
                  reason: "User marked this email pattern as action-bearing from the inbox."
                })
              }
            />
          ))
        ) : (
          <div className="border border-dashed border-hairline bg-surface-1 p-xl text-center">
            <p className="text-heading text-ink">No email in this category</p>
            <p className="mt-xs text-small text-ink-subtle">
              New rule matches and AI classifications will appear here as the inbox is indexed.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
