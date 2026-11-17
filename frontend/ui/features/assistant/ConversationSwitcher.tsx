"use client";

import { useState } from "react";
import type { SessionRow } from "@/ui/client/contracts.generated";
import { useShortDate, useTimeOnly } from "@/ui/client/format";
import { isManagedSession, useSessions } from "@/ui/client/sessions";
import { useAgentCards } from "@/ui/client/work";
import { groupSessions } from "@/ui/features/sessions/sessionGroups";
import { Icon } from "@/ui/icons";
import { LiveDot } from "@/ui/primitives/LiveDot";
import { Mascot } from "@/ui/primitives/Mascot";
import { Popover } from "@/ui/primitives/Popover";
import { BareInput, Pressable } from "@/ui/primitives/Pressable";
import { t } from "@/ui/strings";
import { useAssistant } from "./AssistantProvider";

// The recent ones show; the rest are one search away.
const RECENT_SHOWN = 8;

function Lead({ row }: { row: SessionRow }) {
  const card = (useAgentCards().data?.cards ?? []).find((item) => item.id === row.agent);
  if (isManagedSession(row) && card) return <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} size="sm" />;
  return <Icon name="chat" className="h-3 w-3 text-ink-faint" />;
}

function Row({ row, current, onPick }: { row: SessionRow; current: boolean; onPick: (id: string) => void }) {
  const time = useTimeOnly();
  const day = useShortDate();
  const today = new Date(row.updated).toDateString() === new Date().toDateString();
  return (
    <li>
      <Pressable onClick={() => onPick(row.id)} aria-current={current || undefined} data-testid="conversation-option" className={`focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-md transition-colors duration-fast hover:bg-surface-sunken ${current ? "bg-surface-sunken" : ""}`}>
        <span className="flex w-4 shrink-0 justify-center"><Lead row={row} /></span>
        <span className="min-w-0 flex-1 truncate text-ink-primary">{row.title}</span>
        {row.status === "waiting" ? (
          <span className="flex shrink-0 items-center gap-2 text-sm text-agent-waiting"><LiveDot tone="waiting" />{t("switcher.yourAnswer")}</span>
        ) : row.status === "running" || row.status === "queued" ? (
          <span className="flex shrink-0 items-center gap-2 text-sm text-agent-running"><LiveDot />{t("sessions.status.running")}</span>
        ) : (
          <span className="shrink-0 text-sm tabular-nums text-ink-muted">{today ? time(row.updated) : day(row.updated)}</span>
        )}
      </Pressable>
    </li>
  );
}

function Group({ title, rows, current, onPick }: { title: string; rows: readonly SessionRow[]; current: string | null; onPick: (id: string) => void }) {
  if (!rows.length) return null;
  return (
    // A group, not a landmark: the Sessions page beneath has sections with these same names.
    <div role="group" aria-label={title} className="flex flex-col">
      <h3 className="px-3 pb-1 pt-3 text-sm font-medium text-ink-muted">{title}</h3>
      <ul className="flex flex-col">{rows.map((row) => <Row key={row.id} row={row} current={row.id === current} onPick={onPick} />)}</ul>
    </div>
  );
}

/** Which conversation the chat panel shows: grouped, searchable, roomy. */
export function ConversationSwitcher() {
  const assistant = useAssistant();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [all, setAll] = useState(false);
  const sessions = useSessions(search);
  const rows = sessions.data?.sessions ?? [];
  const current = rows.find((row) => row.id === assistant.session);
  const groups = groupSessions(rows);
  const recent = [...groups.today, ...groups.earlier];
  const shown = all || search ? recent : recent.slice(0, RECENT_SHOWN);
  const today = shown.filter((row) => groups.today.includes(row));
  const earlier = shown.filter((row) => groups.earlier.includes(row));
  const pick = (id: string) => {
    assistant.openSession(id);
    setOpen(false);
  };
  const trigger = (
    <Pressable data-testid="conversation-switcher" className="focus-ring flex min-w-0 max-w-full items-center gap-2 rounded-md px-2 py-1 text-md text-ink-primary transition-colors duration-fast hover:bg-surface-sunken">
      {current?.status === "waiting" ? <LiveDot tone="waiting" /> : current?.status === "running" ? <LiveDot /> : null}
      <span className="min-w-0 truncate"><span className="sr-only">{t("chat.switch")}: </span>{current?.title ?? t("chat.title")}</span>
      <Icon name="chevronDown" className="h-3 w-3 shrink-0 text-ink-muted" />
    </Pressable>
  );
  return (
    <Popover label={t("chat.switch")} trigger={trigger} align="start" size="menu" open={open} onOpenChange={(next) => { setOpen(next); if (!next) { setSearch(""); setAll(false); } }}>
      <div className="flex max-h-popover flex-col">
        <label className="m-2 flex items-center gap-2 rounded-md border border-line-subtle px-3 py-2 text-ink-muted focus-within:border-line-strong">
          <Icon name="search" className="h-3 w-3 shrink-0" />
          <BareInput aria-label={t("switcher.find")} placeholder={t("switcher.find")} value={search} onChange={(event) => setSearch(event.target.value)} className="min-w-0 flex-1 text-md outline-none" />
        </label>
        <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">
          <Group title={t("sessions.waitingOnYou")} rows={groups.waiting} current={assistant.session} onPick={pick} />
          <Group title={t("switcher.agents")} rows={groups.agents} current={assistant.session} onPick={pick} />
          <Group title={t("switcher.today")} rows={today} current={assistant.session} onPick={pick} />
          <Group title={t("switcher.earlier")} rows={earlier} current={assistant.session} onPick={pick} />
          {!rows.length && sessions.isSuccess ? <p className="px-3 py-3 text-md text-ink-muted">{t("switcher.none")}</p> : null}
          {!all && !search && recent.length > RECENT_SHOWN ? (
            <Pressable onClick={() => setAll(true)} className="focus-ring mt-1 w-full rounded-md px-3 py-2 text-center text-sm text-ink-muted transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary">{t("switcher.all", { count: rows.length })}</Pressable>
          ) : null}
        </div>
        <div className="border-t border-line-subtle p-1">
          <Pressable onClick={() => { assistant.newChat(); setOpen(false); }} className="focus-ring flex w-full items-center gap-3 rounded-md px-3 py-2 text-md font-medium text-accent-default transition-colors duration-fast hover:bg-surface-sunken">
            <Icon name="newChat" className="h-4 w-4" />{t("chat.new")}
          </Pressable>
        </div>
      </div>
    </Popover>
  );
}
