"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  BrainCircuit,
  Clock3,
  DatabaseZap,
  Mail,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import { pipelineSteps } from "@/lib/data";
import { isPriorityInboxEmail } from "@/lib/email-filters";
import { useNexusStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const stepIcons = {
  emails: Mail,
  classification: BrainCircuit,
  indexing: DatabaseZap
};

const topNav = [
  { href: "/", label: "Home" },
  { href: "/emails", label: "Emails" }
];

function isActivePath(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || (href === "/emails" && pathname === "/inbox");
}

export function AppHeader() {
  const pathname = usePathname();
  const selectCategory = useNexusStore((state) => state.selectCategory);
  const emails = useNexusStore((state) => state.emails);
  const [activeStep, setActiveStep] = useState(1);
  const priorityUnread = emails.filter((email) => !email.read && isPriorityInboxEmail(email)).length;
  const routeLabel = pathname === "/" ? "Operating picture" : pathname === "/emails" || pathname === "/inbox" ? "Classified inbox" : "Workspace";

  useEffect(() => {
    const interval = window.setInterval(() => {
      setActiveStep((step) => (step + 1) % pipelineSteps.length);
    }, 1600);

    return () => window.clearInterval(interval);
  }, []);

  return (
    <header className="grid h-topbar grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-xl border-b border-hairline bg-canvas px-lg">
      <div className="flex min-w-0 items-center gap-lg">
        <Link href="/" className="flex min-w-[12rem] items-center gap-sm">
          <div className="grid size-2xl place-items-center border border-hairline bg-surface-1 shadow-panel">
            <Bot className="size-md text-accent" />
          </div>
          <div className="min-w-0">
            <h1 className="editorial-display text-heading text-ink">NexusAI</h1>
            <p className="text-caption text-ink-subtle">personal work OS</p>
          </div>
        </Link>

        <nav className="flex items-center gap-md border-l border-hairline pl-lg">
          {topNav.map((item) => {
            const active = isActivePath(pathname, item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => {
                  if (item.href === "/emails") selectCategory("all");
                }}
                className={cn(
                  "relative py-xs text-small transition duration-200 hover:text-ink",
                  active ? "text-ink" : "text-ink-subtle"
                )}
              >
                {item.label}
                {active ? (
                  <motion.span
                    layoutId="top-nav-rule"
                    className="absolute inset-x-0 -bottom-xs h-px bg-accent"
                  />
                ) : null}
              </Link>
            );
          })}
        </nav>
      </div>

      <div className="hidden min-w-0 items-center justify-center xl:flex">
        <div className="grid min-w-[24rem] max-w-[38rem] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-sm border-x border-hairline px-lg">
          <div className="flex items-center gap-xs text-caption text-ink-tertiary">
            <Clock3 className="size-sm text-accent" />
            Today
          </div>
          <div className="min-w-0">
            <p className="truncate text-small text-ink">Next best action: supplier risk reply before 2 PM</p>
            <p className="truncate text-caption text-ink-subtle">{routeLabel} / {priorityUnread} priority unread</p>
          </div>
          <div className="flex items-center gap-xs text-caption text-ink-tertiary">
            <ShieldCheck className="size-sm text-accent" />
            guarded
          </div>
        </div>
      </div>

      <div className="hidden min-w-[22rem] items-center justify-end gap-sm 2xl:flex">
        {pipelineSteps.map((step, index) => {
          const Icon = stepIcons[step.id as keyof typeof stepIcons];
          const isActive = index === activeStep;

          return (
            <div key={step.id} className="flex items-center gap-xs">
              <motion.span
                animate={{ scale: isActive ? 1.08 : 1 }}
                className={cn(
                  "grid size-lg place-items-center border border-hairline",
                  isActive ? "bg-accent text-ink-inverse" : "bg-surface-1 text-ink-tertiary"
                )}
              >
                <Icon className="size-sm" />
              </motion.span>
              <span className={cn("text-caption", isActive ? "text-ink" : "text-ink-subtle")}>
                {step.label}
              </span>
              {index < pipelineSteps.length - 1 ? <div className="h-px w-md bg-hairline" /> : null}
            </div>
          );
        })}
        <Sparkles className="size-sm text-accent" />
      </div>
    </header>
  );
}
