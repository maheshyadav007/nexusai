import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-xs whitespace-nowrap rounded-md text-button transition duration-200 ease-product focus-visible:outline-none focus-visible:shadow-focus disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-md [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-ink-inverse shadow-panel hover:bg-accent-hover",
        secondary:
          "border border-hairline bg-surface-1 text-ink hover:border-hairline-strong hover:bg-surface-2",
        ghost: "text-ink-muted hover:bg-surface-2 hover:text-ink",
        subtle: "bg-surface-2 text-ink-muted hover:bg-surface-3 hover:text-ink",
        danger:
          "border border-status-danger/30 bg-status-danger/10 text-ink hover:bg-status-danger/15",
        icon: "border border-hairline bg-surface-1 text-ink-muted hover:bg-surface-2 hover:text-ink"
      },
      size: {
        sm: "h-xl px-sm",
        md: "h-2xl px-md",
        lg: "h-3xl px-lg",
        icon: "size-2xl p-0",
        "icon-sm": "size-xl p-0"
      }
    },
    defaultVariants: {
      variant: "secondary",
      size: "md"
    }
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
