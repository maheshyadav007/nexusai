"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { UpdateSettings } from "./contracts.generated";

export function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => query("settings.get", {}) });
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: UpdateSettings) => command("settings.update", changes),
    onSuccess: (settings) => client.setQueryData(["settings"], settings),
  });
}
