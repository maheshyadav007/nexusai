"use client";

import {
  Activity,
  AlertTriangle,
  CalendarClock,
  Eye,
  GitPullRequest,
  Inbox,
  MailCheck,
  PanelTop,
  Settings2,
  Sparkles,
  SquareKanban
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AnimatedBullet } from "@/components/dashboard/animated-bullet";
import { ClassifiedEmailCard } from "@/components/dashboard/classified-email-card";
import { PriorityBadge } from "@/components/work/priority-badge";
import { useNexusStore } from "@/lib/store";

const panelIcons = {
  "Important emails": Inbox,
  "Upcoming meetings": CalendarClock,
  "PLM issues": SquareKanban,
  "GitHub / swarm issues": GitPullRequest,
  "Draft emails": MailCheck,
  "Follow-ups": Activity
};

export function EmailOSDashboard() {
  const categories = useNexusStore((state) => state.categories);
  const emails = useNexusStore((state) => state.emails);
  const panels = useNexusStore((state) => state.panels);
  const selectedCategoryId = useNexusStore((state) => state.selectedCategoryId);
  const selectedEmailId = useNexusStore((state) => state.selectedEmailId);
  const selectEmail = useNexusStore((state) => state.selectEmail);
  const toggleEmailRead = useNexusStore((state) => state.toggleEmailRead);
  const addPanel = useNexusStore((state) => state.addPanel);

  const selectedCategory = categories.find((category) => category.id === selectedCategoryId) ?? categories[0];
  const categoryEmails =
    selectedCategoryId === "all"
      ? emails
      : emails.filter((email) => email.categoryId === selectedCategoryId);
  const selectedEmail =
    emails.find((email) => email.id === selectedEmailId) ?? categoryEmails[0] ?? emails[0];
  const importantUnread = emails.filter((email) => !email.read && ["critical", "high"].includes(email.priority));
  const actionBearing = emails.filter((email) => email.categoryId === "action" || email.priority === "critical");

  return (
    <div className="mx-auto max-w-page px-xl py-lg">
      <section className="mb-lg border-b border-hairline pb-lg">
        <div className="flex flex-wrap items-end justify-between gap-lg">
          <div className="max-w-reading">
            <p className="mb-xs text-caption uppercase text-ink-tertiary">No. XXIII / Editorial OS</p>
            <h2 className="editorial-display text-title text-balance text-ink">
              the day, reduced to what needs attention.
            </h2>
          </div>
          <div className="grid grid-cols-2 gap-md text-right">
            <div>
              <p className="editorial-display text-title text-accent">{importantUnread.length}</p>
              <p className="text-caption text-ink-subtle">important unread</p>
            </div>
            <div>
              <p className="editorial-display text-title text-ink">{actionBearing.length}</p>
              <p className="text-caption text-ink-subtle">needs action</p>
            </div>
          </div>
        </div>
      </section>

      <section className="mb-lg grid gap-md xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
        <Card className="p-lg">
          <div className="mb-md flex flex-wrap items-start justify-between gap-md">
            <div>
              <div className="mb-xs flex items-center gap-xs text-caption uppercase text-accent">
                <Inbox className="size-sm" />
                Selected category
              </div>
              <h3 className="text-heading text-ink">{selectedCategory.name}</h3>
              <p className="mt-xxs max-w-reading text-small text-ink-subtle">
                {selectedCategory.unread} unread messages in this category.
              </p>
            </div>
            <div className="flex gap-xs">
              <Badge variant="running">{selectedCategory.unread} unread</Badge>
            </div>
          </div>

          <div className="grid gap-sm">
            {categoryEmails.length > 0 ? (
              categoryEmails.map((email) => (
                <ClassifiedEmailCard
                  key={email.id}
                  email={email}
                  selected={selectedEmail?.id === email.id}
                  onSelect={() => selectEmail(email.id)}
                  onToggleRead={() => toggleEmailRead(email.id)}
                />
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-hairline bg-surface-2 p-lg text-center">
                <p className="text-heading text-ink">No emails yet</p>
                <p className="mt-xs text-small text-ink-subtle">
                  Custom categories will populate as rules and semantic matches start routing messages.
                </p>
              </div>
            )}
          </div>
        </Card>

        <Card className="p-lg">
          <div className="mb-md flex items-center justify-between">
            <div>
              <p className="text-caption uppercase text-accent">Email brief</p>
              <h3 className="mt-xs text-heading text-ink">Summary + key info</h3>
            </div>
            <PriorityBadge priority={selectedEmail.priority} />
          </div>
          <p className="text-small text-ink">{selectedEmail.subject}</p>
          <p className="mt-sm text-small text-ink-subtle">{selectedEmail.summary}</p>

          <div className="mt-md space-y-xs">
            {selectedEmail.keyInfo.map((item) => (
              <div key={item} className="flex items-start gap-xs border-b border-hairline py-sm">
                <Sparkles className="mt-xxs size-sm shrink-0 text-accent" />
                <p className="text-small text-ink-muted">{item}</p>
              </div>
            ))}
          </div>

          <div className="mt-md border border-hairline bg-surface-2 p-sm">
            <div className="mb-xs flex items-center gap-xs text-caption text-ink-tertiary">
              <Settings2 className="size-sm" />
              Why classified here
            </div>
            <div className="flex flex-wrap gap-xxs">
              {selectedEmail.ruleMatches.map((rule) => (
                <Badge key={rule} variant="default">
                  {rule}
                </Badge>
              ))}
            </div>
          </div>

          <div className="mt-md flex gap-xs">
            <Button size="sm" variant="secondary">
              <Eye className="size-sm" />
              Read source
            </Button>
            <Button size="sm" variant="ghost">Draft response</Button>
          </div>
        </Card>
      </section>

      <section className="mb-lg">
        <div className="mb-md flex flex-wrap items-center justify-between gap-md">
          <div>
            <div className="mb-xs flex items-center gap-xs text-caption uppercase text-accent">
              <PanelTop className="size-sm" />
              AI-maintained panels
            </div>
            <h3 className="text-heading text-ink">AI-generated work panels</h3>
            <p className="mt-xxs text-small text-ink-subtle">
              Summaries update in place as email, calendar, PLM, GitHub, and swarm signals change.
            </p>
          </div>
          <Button variant="primary" onClick={addPanel}>
            <PanelTop className="size-sm" />
            Add panel
          </Button>
        </div>

        <div className="grid gap-md xl:grid-cols-3">
          {panels.map((panel) => {
            const Icon = panelIcons[panel.title as keyof typeof panelIcons] ?? AlertTriangle;

            return (
              <Card key={panel.id} className="p-md">
                <div className="mb-md flex items-start justify-between gap-md">
                  <div className="flex min-w-0 items-start gap-sm">
                    <div className="grid size-2xl shrink-0 place-items-center border border-hairline bg-surface-2">
                      <Icon className="size-md text-accent" />
                    </div>
                    <div className="min-w-0">
                      <h4 className="truncate text-heading text-ink">{panel.title}</h4>
                      <p className="text-caption text-ink-tertiary">{panel.category}</p>
                    </div>
                  </div>
                  <PriorityBadge priority={panel.priority} />
                </div>
                <div className="space-y-xs">
                  {panel.items.map((item, index) => (
                    <div key={item} className="border-b border-hairline py-sm">
                      <p className="text-small text-ink-muted">
                        {index === 0 ? (
                          <AnimatedBullet
                            text={item}
                            replacement={`${item} - AI refreshed after the latest inbox pass`}
                            delay={6200}
                          />
                        ) : (
                          item
                        )}
                      </p>
                    </div>
                  ))}
                </div>
                <div className="mt-md flex items-center justify-between gap-sm border-t border-hairline pt-sm">
                  <span className="text-caption text-ink-tertiary">Updated {panel.lastUpdated}</span>
                  <Button size="icon-sm" variant="ghost" aria-label="Panel settings">
                    <Settings2 className="size-sm" />
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}
