import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { Button } from "./Button";

export function ErrorState({ title, description, onRetry }: { title: string; description?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-status-danger p-4">
      <Icon name="error" className="mt-1 h-4 w-4 shrink-0 text-status-danger" />
      <div className="flex flex-col items-start gap-2">
        <p className="text-md font-medium text-ink-primary">{title}</p>
        {description ? <p className="text-md text-ink-secondary">{description}</p> : null}
        {onRetry ? <Button onClick={onRetry}>{t("error.retry")}</Button> : null}
      </div>
    </div>
  );
}
