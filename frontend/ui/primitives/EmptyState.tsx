import type { ReactNode } from "react";
import { Icon, type IconName } from "@/ui/icons";

export function EmptyState({ icon, title, description, action }: { icon: IconName; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 text-ink-secondary">
      <Icon name={icon} className="h-5 w-5 text-ink-muted" />
      <h2 className="text-lg font-medium text-ink-primary">{title}</h2>
      {description ? <p className="max-w-popover text-md text-ink-muted">{description}</p> : null}
      {action}
    </div>
  );
}
