import type { ReactNode } from "react";
import { PageEnter } from "@/ui/primitives/Motion";

/** Next gives this a new key when the top-level section changes, so a new screen arrives once. */
export default function Template({ children }: { children: ReactNode }) {
  return <PageEnter>{children}</PageEnter>;
}
