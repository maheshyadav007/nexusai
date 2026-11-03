"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { post } from "./api";
import type { BackupList, ChooseHome, FolderListing, HomeCheck, HomeStatus, RecoveryKeyView, ResetHome } from "./contracts.generated";

const STARTUP_RETRIES = 100;
const STARTUP_RETRY_MS = 3000;

export function useHomeStatus() {
  // A page opened while the backend is still starting has to wait for it, not give up.
  return useQuery({ queryKey: ["home"], queryFn: () => post<HomeStatus>("/api/home/status", {}), retry: STARTUP_RETRIES, retryDelay: STARTUP_RETRY_MS });
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

export const useCreateFolder = () => useMutation({ mutationFn: (input: { path: string; name: string }) => post<FolderListing>("/api/home/create-folder", input) });
/** "." is wherever the app was started, and the backend works out what that is. */
export const useCurrentFolder = () => useMutation({ mutationFn: () => post<FolderListing>("/api/home/browse", { path: "." }) });

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

function useOpenedHome<I>(path: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: I) => post<HomeStatus>(path, input),
    onSuccess: (status) => {
      client.setQueryData(["home"], status);
      void client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "home" });
    },
  });
}

export const useUnlockHome = () => useOpenedHome<{ recovery_key: string }>("/api/home/unlock");
export const useRestoreBackup = () => useOpenedHome<{ name: string }>("/api/home/restore");

export function useBackups(enabled: boolean) {
  return useQuery({ queryKey: ["home-backups"], queryFn: () => post<BackupList>("/api/home/backups", {}), enabled, staleTime: 0 });
}

const RECOVERY_KEY = ["recovery-key"];

// Never kept around, because it's the one thing that opens this data elsewhere.
export function useRecoveryKey() {
  const ready = useHomeReady();
  return useQuery({ queryKey: RECOVERY_KEY, queryFn: () => post<RecoveryKeyView>("/api/home/recovery-key", {}), enabled: ready, staleTime: 0, gcTime: 0 });
}

function useRecoveryChange(path: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => post<RecoveryKeyView>(path, {}),
    onSuccess: (view) => client.setQueryData(RECOVERY_KEY, view),
  });
}

export const useConfirmRecoveryKey = () => useRecoveryChange("/api/home/recovery-key/confirm");
export const useNewRecoveryKey = () => useRecoveryChange("/api/home/recovery-key/new");

/** Removes everything. The caller reloads afterwards, so nothing in memory outlives it. */
export const useResetEverything = () => useMutation({ mutationFn: (input: ResetHome) => post<HomeStatus>("/api/home/reset", input) });
