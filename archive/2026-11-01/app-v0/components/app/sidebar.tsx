"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, Command, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { navItems } from "@/lib/data";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="desktop-sidebar flex h-screen flex-col border-r border-hairline bg-canvas px-md py-md">
      <Link href="/" className="group mb-xl flex items-center gap-sm rounded-lg px-sm py-xs">
        <span className="grid size-2xl place-items-center rounded-lg border border-hairline bg-surface-1 shadow-panel transition group-hover:border-hairline-strong">
          <Sparkles className="size-md text-accent" />
        </span>
        <span>
          <span className="block text-heading text-ink">NexusAI</span>
          <span className="block text-caption text-ink-subtle">Agentic workspace</span>
        </span>
      </Link>

      <nav className="space-y-xxs">
        {navItems.map((item) => {
          const isActive =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex h-2xl items-center gap-sm rounded-md px-sm text-small text-ink-subtle transition duration-200 ease-product hover:bg-surface-1 hover:text-ink",
                isActive && "bg-surface-2 text-ink shadow-panel"
              )}
            >
              <Icon className="size-md" />
              <span className="min-w-0 flex-1 truncate">{item.title}</span>
              {isActive ? <ChevronRight className="size-sm text-accent" /> : null}
            </Link>
          );
        })}
      </nav>

      <div className="mt-lg rounded-lg border border-hairline bg-surface-1/72 p-sm">
        <div className="mb-sm flex items-center justify-between">
          <div className="flex items-center gap-xs text-caption text-ink-subtle">
            <Command className="size-sm" />
            Focus lane
          </div>
          <Badge variant="success">Live</Badge>
        </div>
        <p className="text-small text-ink-muted">
          Executive email triage, release blockers, and calendar conflicts are being watched.
        </p>
      </div>

      <div className="mt-auto rounded-xl border border-hairline bg-surface-1 p-md shadow-panel">
        <div className="mb-md flex items-center gap-sm">
          <div className="grid size-2xl place-items-center rounded-full bg-accent-soft text-button text-ink">
            MY
          </div>
          <div className="min-w-0">
            <p className="truncate text-small text-ink">Mahesh Yadav</p>
            <p className="truncate text-caption text-ink-subtle">Product workspace</p>
          </div>
        </div>
        <Button className="w-full justify-between" variant="secondary" size="sm">
          Command center
          <span className="rounded-sm border border-hairline px-xs py-xxs text-caption text-ink-subtle">
            Cmd K
          </span>
        </Button>
      </div>
    </aside>
  );
}
