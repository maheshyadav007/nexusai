import NextLink from "next/link";
import type { ComponentProps } from "react";

export function TextLink({ className = "", ...props }: ComponentProps<typeof NextLink>) {
  return <NextLink className={`focus-ring rounded-sm text-accent-default underline underline-offset-2 transition-colors duration-fast hover:text-accent-hover ${className}`} {...props} />;
}
