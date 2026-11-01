import { cn } from "@/lib/utils";

type ProgressProps = {
  value: number;
  className?: string;
};

export function Progress({ value, className }: ProgressProps) {
  return (
    <div className={cn("h-xs overflow-hidden rounded-full bg-surface-3", className)}>
      <div
        className="h-full rounded-full bg-accent transition-all duration-500 ease-product"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
