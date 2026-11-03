"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { query } from "./api";
import type { GenerationState } from "./contracts.generated";

export type GenerationPhase = "preparing" | NonNullable<GenerationState["phase"]>;

/** Snapshot on opening/reconnection; subsequent phases arrive over the shared event stream. */
export function useGeneration(kind: "trace" | "session", id: string | null) {
  return useQuery({
    queryKey: ["generation", kind, id],
    queryFn: () => query("generation.get", kind === "trace" ? { trace_id: id } : { session: id }),
    enabled: Boolean(id),
    staleTime: 0,
  });
}

/** A request being prepared is not yet a model generating. Each attempt has its own trace. */
export function useGenerationCommand<I, R>(run: (input: I, trace: string) => Promise<R>) {
  const [trace, setTrace] = useState<string | null>(null);
  const generation = useGeneration("trace", trace);
  const mutation = useMutation({
    mutationFn: (input: I) => {
      // Also works over plain HTTP, where randomUUID isn't available.
      const next = `generation-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setTrace(next);
      return run(input, next);
    },
  });
  const phase: GenerationPhase = mutation.isPending ? generation.data?.phase ?? "preparing" : "idle";
  return { ...mutation, phase: phase === "idle" && mutation.isPending ? "preparing" as const : phase };
}
