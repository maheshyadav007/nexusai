"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { post } from "./api";
import type { ChooseHome, FolderListing, HomeCheck, HomeStatus } from "./contracts.generated";

export function useHomeStatus() {
  return useQuery({ queryKey: ["home"], queryFn: () => post<HomeStatus>("/api/home/status", {}) });
}

export function useHomeReady(): boolean {
  return useHomeStatus().data?.state === "ready";
}

export function useHomeCheck(path: string) {
  return useQuery({
    queryKey: ["home-check", path],
    queryFn: () => post<HomeCheck>("/api/home/check", { path }),
    enabled: path.trim().length > 0,
    staleTime: 0,
  });
}

export function useFolders(path: string | null, enabled: boolean, extension?: string) {
  return useQuery({
    queryKey: ["home-folders", path, extension],
    queryFn: () => post<FolderListing>("/api/home/browse", { path, ...(extension ? { extension } : {}) }),
    enabled,
    staleTime: 0,
  });
}

export function useChooseHome() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: ChooseHome) => post<HomeStatus>("/api/home/choose", input),
    onSuccess: (status) => {
      client.setQueryData(["home"], status);
      // Everything asked before Home was open is now out of date.
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "home" });
    },
  });
}
