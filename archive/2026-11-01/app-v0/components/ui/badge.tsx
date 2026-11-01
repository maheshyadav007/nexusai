import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-xxs rounded-full border px-xs py-xxs text-caption transition duration-200",
  {
    variants: {
      variant: {
        default: "border-hairline bg-surface-2 text-ink-muted",
        critical: "border-status-danger/30 bg-status-danger/10 text-ink",
        high: "border-status-warning/30 bg-status-warning/10 text-ink",
        medium: "border-status-info/30 bg-status-info/10 text-ink-muted",
        low: "border-hairline bg-surface-2 text-ink-subtle",
        success: "border-status-success/30 bg-status-success/10 text-ink",
        running: "border-accent/30 bg-accent/10 text-ink",
        failed: "border-status-danger/30 bg-status-danger/10 text-ink"
      }
    },
    defaultVariants: {
      variant: "default"
    }
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
