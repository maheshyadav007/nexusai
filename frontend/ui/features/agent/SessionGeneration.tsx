"use client";

import { useGeneration } from "@/ui/client/generation";
import { useSessions } from "@/ui/client/sessions";
import { GenerationSurface } from "@/ui/primitives/GenerationSurface";
import { t } from "@/ui/strings";

/** Background work stays visible after its start request has returned. */
export function SessionGeneration({ session }: { session: string | null | undefined }) {
  const sessions = useSessions("");
  const generation = useGeneration("session", session ?? null);
  const row = sessions.data?.sessions.find((item) => item.id === session);
  if (!row || (row.status !== "running" && row.status !== "queued")) return null;
  const phase = generation.data?.phase;
  if (phase !== "queued" && phase !== "generating") return <p role="status" className="text-sm text-ink-muted">{t(row.status === "queued" ? "generation.runQueued" : "generation.tools")}</p>;
  return <GenerationSurface phase={phase} label={t("generation.answer")} compact />;
}
