"use client";

import { motion } from "framer-motion";
import { usePathname, useRouter } from "next/navigation";
import {
  AlertCircle,
  Archive,
  BellPlus,
  BriefcaseBusiness,
  ChevronRight,
  Crown,
  FolderPlus,
  Inbox,
  Plus,
  Radar,
  Sparkles,
  SquareKanban,
  UsersRound
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { getEmailsForCategory, isPriorityInboxEmail } from "@/lib/email-filters";
import { useNexusStore } from "@/lib/store";
import type { EmailCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

const categoryIcons = {
  all: Archive,
  priority: Radar,
  action: AlertCircle,
  exec: Crown,
  customer: UsersRound,
  release: SquareKanban,
  engineering: BriefcaseBusiness,
  watch: BellPlus
};

const categoryGroups = [
  {
    title: "Smart views",
    ids: ["priority", "action", "all"]
  },
  {
    title: "Source views",
    ids: ["exec", "customer", "release", "engineering"]
  },
  {
    title: "Personal",
    ids: ["watch"]
  }
];

export function ClassificationSidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const categories = useNexusStore((state) => state.categories);
  const emails = useNexusStore((state) => state.emails);
  const selectedCategoryId = useNexusStore((state) => state.selectedCategoryId);
  const selectCategory = useNexusStore((state) => state.selectCategory);
  const createCategory = useNexusStore((state) => state.createCategory);
  const unreadTotal = emails.filter((email) => !email.read).length;
  const priorityInbox = emails.filter(isPriorityInboxEmail);
  const priorityCategory = categories.find((category) => category.id === "priority");

  const handleSelectCategory = (id: string) => {
    selectCategory(id);
    if (pathname !== "/emails" && pathname !== "/inbox") {
      router.push("/emails");
    }
  };

  return (
    <aside className="desktop-sidebar h-[calc(100vh-var(--layout-topbar))] overflow-y-auto border-r border-hairline bg-canvas px-md py-lg">
      <button
        type="button"
        onClick={() => handleSelectCategory("priority")}
        className="mb-md w-full border border-hairline bg-surface-1 p-sm text-left transition hover:border-hairline-strong hover:bg-surface-2"
      >
        <div className="mb-sm flex items-start justify-between gap-sm">
          <div>
            <div className="mb-xxs flex items-center gap-xs text-caption uppercase text-accent">
              <Sparkles className="size-sm" />
              Focus queue
            </div>
            <p className="text-small text-ink">Priority inbox</p>
          </div>
          <ChevronRight className="size-sm text-ink-tertiary" />
        </div>
        <div className="grid grid-cols-2 border-t border-hairline pt-sm">
          <div className="border-r border-hairline pr-sm">
            <p className="editorial-display text-heading text-accent">{priorityCategory?.count ?? priorityInbox.length}</p>
            <p className="text-caption text-ink-subtle">focus items</p>
          </div>
          <div className="pl-sm">
            <p className="editorial-display text-heading text-ink">{unreadTotal}</p>
            <p className="text-caption text-ink-subtle">unread</p>
          </div>
        </div>
      </button>

      <div className="mb-md flex items-center justify-between border-b border-hairline pb-sm">
        <div>
          <div className="flex items-center gap-xs">
            <Inbox className="size-md text-accent" />
            <p className="text-small text-ink">Attention router</p>
          </div>
          <p className="mt-xxs text-caption text-ink-subtle">Choose what the OS should reason over.</p>
        </div>
        <Button aria-label="Create category" size="icon-sm" variant="ghost" onClick={createCategory}>
          <Plus className="size-sm" />
        </Button>
      </div>

      <div className="space-y-md">
        {categoryGroups.map((group) => {
          const groupCategories = group.ids
            .map((id) => categories.find((category) => category.id === id))
            .filter((category): category is EmailCategory => Boolean(category));

          return (
            <section key={group.title}>
              <p className="mb-xs text-caption uppercase text-ink-tertiary">{group.title}</p>
              <div className="space-y-xxs">
                {groupCategories.map((category) => {
                  const Icon = categoryIcons[category.id as keyof typeof categoryIcons] ?? Inbox;
                  const isActive = selectedCategoryId === category.id;
                  const categoryEmails = getEmailsForCategory(emails, category.id);
                  const computedUnread = categoryEmails.filter((email) => !email.read).length;
                  const count = category.count || categoryEmails.length;
                  const unread = category.unread || computedUnread;

                  return (
                    <button
                      key={category.id}
                      type="button"
                      onClick={() => handleSelectCategory(category.id)}
                      className={cn(
                        "relative w-full border-b border-hairline px-sm py-sm text-left transition duration-200 ease-product hover:bg-surface-1",
                        isActive && "bg-surface-1"
                      )}
                    >
                      {isActive ? (
                        <motion.span
                          layoutId="category-active-rule"
                          className="absolute bottom-sm left-0 top-sm w-px bg-accent"
                        />
                      ) : null}
                      <div className="mb-xs flex items-center justify-between gap-sm">
                        <span className="flex min-w-0 items-center gap-xs">
                          <Icon className={cn("size-sm shrink-0", isActive ? "text-accent" : "text-ink-tertiary")} />
                          <span className="truncate text-small text-ink">{category.name}</span>
                        </span>
                        <span className={cn("text-caption", unread > 0 ? "text-accent" : "text-ink-tertiary")}>
                          {count}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-sm">
                        <p className="line-clamp-1 text-caption text-ink-subtle">{category.description}</p>
                        <span className="shrink-0 text-caption text-ink-tertiary">{unread} unread</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      <Button className="mt-md w-full justify-between" variant="secondary" onClick={createCategory}>
        <FolderPlus className="size-sm" />
        Create routing rule
        <ChevronRight className="size-sm" />
      </Button>
    </aside>
  );
}
