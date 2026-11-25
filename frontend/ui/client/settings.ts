"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { PriorityShows, SidebarLayout, UpdateSettings } from "./contracts.generated";
import { useHomeReady } from "./home";

/** What the Priority view can bring in, in the order its menu lists them. */
export type PriorityShow = PriorityShows[number];
export const PRIORITY_SHOWS: readonly PriorityShow[] = ["waiting_on_you", "waiting_on_others", "important", "folders", "unfiled"];
// The backend's default too (PRIORITY_SHOWS_DEFAULT in contracts/settings.py).
export const PRIORITY_SHOWS_DEFAULT: readonly PriorityShow[] = ["waiting_on_you", "waiting_on_others", "important"];

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
