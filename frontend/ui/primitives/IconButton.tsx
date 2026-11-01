import type { ButtonHTMLAttributes, Ref } from "react";
import { Icon, type IconName } from "@/ui/icons";
import { Tooltip } from "./Tooltip";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string;
  /** Off for close buttons: a tooltip inside an overlay takes the first Escape press. */
  tooltip?: boolean;
  ref?: Ref<HTMLButtonElement>;
}

export function IconButton({ icon, label, tooltip = true, className = "", ...props }: IconButtonProps) {
  const button = (
    <button
      type="button"
      aria-label={label}
      className={`focus-ring inline-flex items-center justify-center rounded-md p-2 text-ink-secondary transition-colors duration-fast hover:bg-surface-sunken hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
      {...props}
    >
      <Icon name={icon} />
    </button>
  );
  return tooltip ? <Tooltip content={label}>{button}</Tooltip> : button;
}
