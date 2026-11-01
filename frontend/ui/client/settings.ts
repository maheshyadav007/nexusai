"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { UpdateSettings } from "./contracts.generated";
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
