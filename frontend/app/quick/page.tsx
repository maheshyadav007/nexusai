import type { Metadata } from "next";
import { QuickAsk } from "@/ui/features/assistant/QuickAsk";
import { QuickWindow } from "@/ui/shell/QuickWindow";
import { t } from "@/ui/strings";

export const metadata: Metadata = { title: t("quick.window") };

/** The desktop app's quick-ask box. It has a small window of its own, with no app around it. */
export default function QuickPage() {
  return (
    <QuickWindow>
      <QuickAsk />
    </QuickWindow>
  );
}
