"use client";

import Link from "next/link";
import { useId, type ReactNode } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { ActiveMark } from "@/ui/primitives/Motion";
import { Pressable } from "@/ui/primitives/Pressable";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { t } from "@/ui/strings";

/** Whether the AI reads what's in a folder. Its icon wears the accent when it does. */
export type FolderTone = "ai" | "partly" | "kept" | "label";

const TONE_ICON: Record<FolderTone, string> = { ai: "text-accent-default", partly: "text-accent-default", kept: "text-ink-faint", label: "text-ink-faint" };
const TONE_TEXT = { ai: "nav.folder.tone.ai", partly: "nav.folder.tone.partly", kept: "nav.folder.tone.kept", label: "nav.folder.tone.label" } as const;

// Each level sets its icon under the label above it. Deeper ones stay at the last step.
const INDENT = ["", "pl-5", "pl-7"] as const;

/** One folder in the sidebar: every kind looks the same, and only its icon's color says whether
 *  the AI reads it. A folder holding others folds them with the arrow at its end. */
export function FolderLink({ href, icon, tone, label, unread, active, depth = 0, fold, detail, menu = (link) => link }: {
  href: string;
  icon: IconName;
  tone: FolderTone;
  label: string;
  unread?: number;
  active: boolean;
  depth?: number;
  fold?: { open: boolean; toggle: () => void };
  /** More said about it, such as how it's filed. */
  detail?: string;
  /** Wraps the link, such as in its right-click menu. */
  menu?: (link: ReactNode) => ReactNode;
}) {
  const id = useId();
  const about = t(TONE_TEXT[tone]);
  return (
    <div className={`flex items-center ${INDENT[Math.min(depth, INDENT.length - 1)]}`}>
      {/* Named by its visible label; what kind of folder it is, and its unread count, are described. */}
      <span id={`${id}-about`} hidden>{detail ? `${about}. ${detail}` : about}</span>
      {unread ? <span id={`${id}-new`} hidden>{t("nav.count.quiet", { count: unread })}</span> : null}
      {menu(<Link
        href={href}
        aria-current={active ? "page" : undefined}
        aria-describedby={[`${id}-about`, ...(unread ? [`${id}-new`] : [])].join(" ")}
        className={`focus-ring press relative flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-px text-md transition-colors duration-fast ${active ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}
      >
        {active ? <ActiveMark group="nav-active" /> : null}
        <Tooltip content={about} side="right">
          <span aria-hidden className={`relative flex shrink-0 ${TONE_ICON[tone]}`}><Icon name={icon} /></span>
        </Tooltip>
        <span className="relative min-w-0 flex-1 truncate">{label}</span>
        {unread ? <span aria-hidden className="relative text-sm tabular-nums text-ink-muted">{unread.toLocaleString()}</span> : null}
      </Link>)}
      {fold ? (
        <Pressable aria-expanded={fold.open} aria-label={t(fold.open ? "nav.folder.fold" : "nav.folder.unfold", { name: label })} onClick={fold.toggle} className="focus-ring ml-px flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-raised hover:text-ink-primary">
          <Icon name="chevronDown" className={`h-3 w-3 transition-transform duration-fast ${fold.open ? "" : "-rotate-90"}`} />
        </Pressable>
      ) : null}
    </div>
  );
}
