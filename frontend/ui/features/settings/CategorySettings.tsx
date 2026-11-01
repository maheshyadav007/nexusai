"use client";

import { useCategories, useRemoveCategory, useSaveCategory } from "@/ui/client/mail";
import { Card } from "@/ui/primitives/Card";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { IconButton } from "@/ui/primitives/IconButton";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Switch } from "@/ui/primitives/Switch";
import { t, tn } from "@/ui/strings";

const SOURCE = { user: "categories.source.user", agent: "categories.source.agent", rule: "categories.source.rule" } as const;

export function CategorySettings() {
  const categories = useCategories();
  const save = useSaveCategory();
  const remove = useRemoveCategory();
  const rows = (categories.data?.categories ?? []).filter((item) => !item.proposed);
  return (
    <Card title={t("nav.categories")} description={t("categories.description")}>
      {categories.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {categories.isError ? <ErrorState title={t("categories.error")} onRetry={() => void categories.refetch()} /> : null}
      {categories.isSuccess && rows.length === 0 ? <EmptyState icon="categories" title={t("categories.empty")} /> : null}
      <ul className="flex flex-col">
        {rows.map((item) => (
          <li key={item.name} data-testid="category" className="flex items-center gap-4 border-b border-line-subtle py-3 first:pt-0 last:border-b-0 last:pb-0">
            <div className="min-w-0 flex-1">
              <p className="truncate text-md text-ink-primary">{item.name}</p>
              <p className="truncate text-sm tabular-nums text-ink-muted">
                {t(SOURCE[item.source])} · {tn("categories.count", item.count ?? 0)}
                {item.sender ? ` · ${t("categories.from", { sender: item.sender })}` : ""}
              </p>
            </div>
            <Switch label={t("categories.priority")} checked={item.in_priority} onChange={(in_priority) => save.mutate({ name: item.name, in_priority, ...(item.sender ? { sender: item.sender } : {}), ...(item.subject ? { subject: item.subject } : {}) })} />
            <IconButton icon="trash" label={t("tasks.remove", { title: item.name })} onClick={() => remove.mutate(item.name)} />
          </li>
        ))}
      </ul>
    </Card>
  );
}
