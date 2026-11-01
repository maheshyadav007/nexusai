import { Icon } from "@/ui/icons";

export function OfflineNotice({ message }: { message: string }) {
  return (
    <div role="status" className="flex items-center gap-2 rounded-md bg-surface-sunken px-3 py-2 text-md text-ink-secondary">
      <Icon name="offline" />
      {message}
    </div>
  );
}
