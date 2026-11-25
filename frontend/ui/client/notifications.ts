"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import { useHomeReady } from "./home";

export function useNotifications(kind: string | null) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["notifications", kind], queryFn: () => query("notifications.list", { kind }), enabled: ready });
}

export function useClearNotifications() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (kind: string | null) => command("notifications.clear", { kind }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useRestoreNotifications() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ids: number[]) => command("notifications.restore", { ids }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number | null) => command("notifications.markRead", { id }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["notifications"] }),
  });
}
