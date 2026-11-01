"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { SidebarLayout, UpdateSettings } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useSettings() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["settings"], queryFn: () => query("settings.get", {}), enabled: ready });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: UpdateSettings) => command("settings.update", changes),
    onSuccess: (settings) => client.setQueryData(["settings"], settings),
  });
}

export function useSidebar() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["sidebar"], queryFn: () => query("sidebar.get", {}), enabled: ready });
}

export function useUpdateSidebar() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (layout: SidebarLayout) => command("sidebar.update", layout),
    // Shown at once, so a dragged row doesn't jump back while saving.
    onMutate: (layout) => client.setQueryData(["sidebar"], layout),
  });
}

export function useResetSidebar() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => command("sidebar.reset", {}),
    onSuccess: (layout) => client.setQueryData(["sidebar"], layout),
  });
}
