"use client";

import { useMemo, useState } from "react";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Input } from "@/ui/primitives/Input";
import { Menu } from "@/ui/primitives/Menu";
import { Popover } from "@/ui/primitives/Popover";
import { Pressable } from "@/ui/primitives/Pressable";
import { t, type StringKey } from "@/ui/strings";

export interface Chosen {
  sender?: string;
  days?: number;
  from?: string;
  to?: string;
  folder?: string;
  category?: string;
  attachment?: boolean;
  fileType?: string;
}

export interface FilterOption {
  value: string;
  label: string;
  count?: number;
}

const DAY_MS = 86_400_000;
const PRESETS: readonly { days: number; label: StringKey }[] = [
  { days: 1, label: "search.date.day" },
  { days: 7, label: "search.date.week" },
  { days: 30, label: "search.date.month" },
  { days: 365, label: "search.date.year" },
];
// Words like from:priya can go straight in the search box.
const FROM_WORD = /(?:^|\s)from:(\S+)/i;

/** Takes from:someone out of what was typed, so it can become a filter. */
export function parseQuery(text: string): { words: string; sender?: string } {
  const found = FROM_WORD.exec(text);
  if (!found) return { words: text };
  return { words: text.replace(FROM_WORD, " ").trim(), sender: found[1] ?? "" };
}

export function datesOf(chosen: Chosen): { date_from?: string; date_to?: string } {
  if (chosen.days) return { date_from: new Date(Date.now() - chosen.days * DAY_MS).toISOString() };
  return { ...(chosen.from ? { date_from: chosen.from } : {}), ...(chosen.to ? { date_to: `${chosen.to}T23:59:59` } : {}) };
}

function Chip({ label, active, onClear, children }: { label: string; active: boolean; onClear?: (() => void) | undefined; children?: never }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm transition-colors duration-fast ${active ? "border-accent-default text-accent-default" : "border-line-subtle text-ink-secondary hover:bg-surface-sunken"}`}>
      {label}
      {active && onClear ? null : <Icon name="chevronDown" className="h-3 w-3" />}
    </span>
  );
}

function Clear({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <Pressable aria-label={t("search.clear", { filter: label })} className="-ml-1 rounded-full p-1 text-ink-muted hover:text-ink-primary" onClick={onClear}>
      <Icon name="close" className="h-3 w-3" />
    </Pressable>
  );
}

function PickFrom({ label, value, options, onChoose }: { label: string; value?: string | undefined; options: readonly FilterOption[]; onChoose: (value: string | undefined) => void }) {
  const shown = options.find((option) => option.value === value)?.label ?? value;
  const trigger = <Pressable aria-label={label} className="rounded-full"><Chip label={shown ? `${label}: ${shown}` : label} active={Boolean(value)} /></Pressable>;
  return (
    <span className="inline-flex items-center gap-1">
      <Menu trigger={trigger} items={options.map((option) => ({ id: option.value, label: option.count === undefined ? option.label : `${option.label} (${option.count.toLocaleString()})`, onSelect: () => onChoose(option.value) }))} />
      {value ? <Clear label={label} onClear={() => onChoose(undefined)} /> : null}
    </span>
  );
}

/** Filters as a row of chips, the same for mail and documents. Only what applies is passed in. */
export function SearchFilters({ chosen, onChange, folders, categories, fileTypes, withAttachment = false }: { chosen: Chosen; onChange: (next: Chosen) => void; folders?: readonly FilterOption[]; categories?: readonly FilterOption[]; fileTypes?: readonly FilterOption[]; withAttachment?: boolean }) {
  const [sender, setSender] = useState(chosen.sender ?? "");
  const set = (changes: Partial<Chosen>) => {
    const next: Chosen = { ...chosen, ...changes };
    for (const key of Object.keys(next) as (keyof Chosen)[]) if (next[key] === undefined) delete next[key];
    onChange(next);
  };
  const dateLabel = useMemo(() => {
    const preset = PRESETS.find((item) => item.days === chosen.days);
    if (preset) return t(preset.label);
    if (chosen.from || chosen.to) return [chosen.from, chosen.to].filter(Boolean).join(" – ");
    return null;
  }, [chosen.days, chosen.from, chosen.to]);
  const fromLabel = t("search.sender");
  const dateName = t("search.date");
  return (
    <div role="group" aria-label={t("search.filters")} className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1">
        <Popover label={fromLabel} trigger={<Pressable aria-label={fromLabel} className="rounded-full"><Chip label={chosen.sender ? `${fromLabel}: ${chosen.sender}` : fromLabel} active={Boolean(chosen.sender)} /></Pressable>}>
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const clean = sender.trim();
              if (clean) set({ sender: clean });
              else set({ sender: undefined });
            }}
          >
            <Input aria-label={fromLabel} placeholder={t("search.sender.placeholder")} value={sender} onChange={(event) => setSender(event.target.value)} />
            <Button type="submit">{t("search.apply")}</Button>
          </form>
        </Popover>
        {chosen.sender ? <Clear label={fromLabel} onClear={() => { setSender(""); set({ sender: undefined }); }} /> : null}
      </span>
      <span className="inline-flex items-center gap-1">
        <Popover label={dateName} trigger={<Pressable aria-label={dateName} className="rounded-full"><Chip label={dateLabel ? `${dateName}: ${dateLabel}` : dateName} active={Boolean(dateLabel)} /></Pressable>}>
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-1">
              {PRESETS.map((item) => (
                <Button key={item.days} variant="quiet" className="py-px" aria-pressed={chosen.days === item.days} onClick={() => set({ days: item.days, from: undefined, to: undefined })}>{t(item.label)}</Button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <Input type="date" aria-label={t("search.from")} value={chosen.from ?? ""} onChange={(event) => set({ days: undefined, from: event.target.value || undefined })} />
              <Input type="date" aria-label={t("search.until")} value={chosen.to ?? ""} onChange={(event) => set({ days: undefined, to: event.target.value || undefined })} />
            </div>
          </div>
        </Popover>
        {dateLabel ? <Clear label={dateName} onClear={() => set({ days: undefined, from: undefined, to: undefined })} /> : null}
      </span>
      {folders?.length ? <PickFrom label={t("search.folder")} value={chosen.folder} options={folders} onChoose={(folder) => set({ folder })} /> : null}
      {categories?.length ? <PickFrom label={t("search.category")} value={chosen.category} options={categories} onChoose={(category) => set({ category })} /> : null}
      {fileTypes?.length ? <PickFrom label={t("search.fileType")} value={chosen.fileType} options={fileTypes} onChoose={(fileType) => set({ fileType })} /> : null}
      {withAttachment ? (
        <Pressable aria-pressed={Boolean(chosen.attachment)} className="rounded-full" onClick={() => set({ attachment: chosen.attachment ? undefined : true })}>
          <Chip label={t("search.attachments")} active={Boolean(chosen.attachment)} onClear={() => undefined} />
        </Pressable>
      ) : null}
    </div>
  );
}

/** Marks the words someone searched for inside a piece of text. */
export function Highlight({ text, words }: { text: string; words: string }) {
  const terms = words.trim().split(/\s+/).filter((word) => word.length > 1).map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(`(${terms.join("|")})`, "gi");
  return (
    <>
      {text.split(pattern).map((piece, index) => (index % 2 ? <mark key={`${index}-${piece}`} className="rounded-sm bg-surface-sunken font-medium text-ink-primary">{piece}</mark> : piece))}
    </>
  );
}
