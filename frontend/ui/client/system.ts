"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { command, query } from "./api";
import type { SearchLogs } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useLogs(filters: SearchLogs) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["logs", filters], queryFn: () => query("logs.search", filters), enabled: ready });
}

export function useTrace(traceId: string | null) {
  return useQuery({ queryKey: ["trace", traceId], queryFn: () => query("trace.get", { trace_id: traceId ?? "" }), enabled: Boolean(traceId), staleTime: 0 });
}

export function useDiagnostics() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["diagnostics"], queryFn: () => query("diagnostics.get", {}), enabled: ready, staleTime: 0 });
}

export const useNetworkCheck = () => useMutation({ mutationFn: () => command("network.check", {}) });
