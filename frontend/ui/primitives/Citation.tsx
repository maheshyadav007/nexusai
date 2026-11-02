"use client";

import type { ReactNode } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { Popover } from "./Popover";
import { Pressable } from "./Pressable";
import { Tooltip } from "./Tooltip";

/** A small number after a statement, naming its source on hover and opening it on click. */
export function CitationMark({ number, title, label, onOpen }: { number: string; title?: string | undefined; label: string; onOpen?: (() => void) | undefined }) {
  const mark = (
    <Pressable aria-label={label} onClick={onOpen} className="mx-px rounded-sm align-super text-xs tabular-nums text-accent-default underline-offset-2 hover:underline">
      {number}
    </Pressable>
  );
  return title ? <Tooltip content={title}>{mark}</Tooltip> : mark;
}

export interface SourceRow {
  id: string;
  icon: IconName;
  title: string;
  detail: string;
  number?: number | null | undefined;
  onOpen: () => void;
}

function Row({ source }: { source: SourceRow }) {
  return (
    <li data-testid="source-row">
      <Pressable onClick={source.onOpen} className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left transition-colors duration-fast hover:bg-surface-sunken">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-surface-sunken text-ink-muted"><Icon name={source.icon} className="h-3 w-3" /></span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-md text-ink-primary">{source.number ? `${source.number}. ` : ""}{source.title}</span>
          {source.detail ? <span className="truncate text-sm text-ink-muted">{source.detail}</span> : null}
        </span>
      </Pressable>
    </li>
  );
}

// After Beautiful UI's Streaming Text: the count with a few tiles, and the list a click away.
const TILES_SHOWN = 3;

/** How many sources an answer drew on. It stays in view when the rest of the action bar hides. */
export function SourcesPill({ label, sources, heading, children }: { label: string; sources: readonly SourceRow[]; heading?: { cited: string; read: string }; children?: ReactNode }) {
  const cited = sources.filter((source) => source.number);
  const read = sources.filter((source) => !source.number);
  return (
    <Popover
      label={label}
      trigger={
        <Pressable data-testid="sources-pill" aria-label={label} className="inline-flex items-center gap-1 rounded-full border border-line-subtle py-px pl-1 pr-2 text-sm tabular-nums text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken">
          <span className="flex -space-x-1">
            {sources.slice(0, TILES_SHOWN).map((source) => (
              <span key={source.id} className="flex h-4 w-4 items-center justify-center rounded-sm border border-surface-page bg-surface-sunken text-ink-muted">
                <Icon name={source.icon} className="h-3 w-3" />
              </span>
            ))}
          </span>
          {label}
        </Pressable>
      }
    >
      <div className="flex max-h-popover flex-col gap-2 overflow-y-auto">
        {cited.length ? (
          <section>
            {heading && read.length ? <h3 className="px-2 pb-1 text-sm text-ink-muted">{heading.cited}</h3> : null}
            <ul>{cited.map((source) => <Row key={source.id} source={source} />)}</ul>
          </section>
        ) : null}
        {read.length ? (
          <section>
            {heading ? <h3 className="px-2 pb-1 text-sm text-ink-muted">{heading.read}</h3> : null}
            <ul>{read.map((source) => <Row key={source.id} source={source} />)}</ul>
          </section>
        ) : null}
        {children}
      </div>
    </Popover>
  );
}
