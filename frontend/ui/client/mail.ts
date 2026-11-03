"use client";

import { useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { Importance, Draft, ListThreads, MailProfile, MoveThread, RuleSet, SaveCategory, SearchMail, SetThreadStatus, UpdateCategory } from "./contracts.generated";
import { useHomeReady } from "./home";

export type FolderRole = NonNullable<ListThreads["folder"]>;
export type ThreadStatus = SetThreadStatus["status"];

export function useMailStatus() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-status"], queryFn: () => query("mail.status", {}), enabled: ready });
}

export function useMailAccounts() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-accounts"], queryFn: () => query("mail.accounts", {}), enabled: ready });
}

export const useTestAccount = () =>
  useMutation({ mutationFn: (input: { profile: MailProfile; password?: string | null }) => command("mail.accounts.test", input) });

export function useSaveAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; profile: MailProfile; password?: string | null; pull_limit?: number | null }) => command("mail.accounts.save", input),
    onSuccess: (accounts) => client.setQueryData(["mail-accounts"], accounts),
  });
}

export function useSetNeverDelete() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (value: boolean) => command("mail.sync.neverDelete", { value }),
    onSuccess: (status) => client.setQueryData(["mail-status"], status),
  });
}

export function useGetMoreFromFolder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { folder: string; count?: number | null }) => command("mail.history.more", input),
    onSuccess: (status) => {
      client.setQueryData(["mail-status"], status);
      void client.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
}

export function useSetSenderImages() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { address: string; allow: boolean }) => command("mail.images.sender", input),
    onSuccess: () => client.invalidateQueries({ queryKey: ["thread"] }),
  });
}

export function useMailFolders() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-folders"], queryFn: () => query("mail.folders", {}), enabled: ready });
}

export function useRemoveAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => command("mail.accounts.remove", { name }),
    onSuccess: (accounts) => client.setQueryData(["mail-accounts"], accounts),
  });
}

export const PAGE_SIZE = 100;

/** One page of a list by where it starts, so a scrollbar can jump anywhere and only what's on screen reloads. */
export function useThreadPages(folder: FolderRole, category: string | null, location: string | null, pages: readonly number[]) {
  const ready = useHomeReady();
  return useQueries({
    queries: pages.map((page) => ({
      queryKey: ["threads", folder, category, location, "page", page],
      queryFn: () => query("threads.list", { folder, category, location, offset: page * PAGE_SIZE, limit: PAGE_SIZE }),
      enabled: ready,
    })),
  });
}

export function useThreads(folder: FolderRole, category: string | null, location: string | null = null) {
  const ready = useHomeReady();
  return useInfiniteQuery({
    queryKey: ["threads", folder, category, location],
    queryFn: ({ pageParam }) => query("threads.list", { folder, category, location, before: pageParam, limit: PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_before ?? null,
    enabled: ready,
  });
}

export function useThread(id: number) {
  return useQuery({ queryKey: ["thread", id], queryFn: () => query("thread.get", { id }) });
}

function useThreadCommand<T>(run: (input: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["threads"] });
      void client.invalidateQueries({ queryKey: ["thread"] });
    },
  });
}

export const useSetRead = () => useThreadCommand((input: { id: number; read: boolean }) => command("thread.setRead", input));
export const useSetFlag = () => useThreadCommand((input: { id: number; flagged: boolean }) => command("thread.setFlag", input));
export const useAddToFolder = () => useThreadCommand((input: { id: number; folder: string }) => command("thread.addToFolder", input));
export const useRemoveFromFolder = () => useThreadCommand((input: { id: number; folder: string }) => command("thread.removeFromFolder", input));
export const useAddCategory = () => useThreadCommand((input: { id: number; name: string }) => command("thread.addCategory", input));
export const useRemoveThreadCategory = () => useThreadCommand((input: { id: number; name: string }) => command("thread.removeCategory", input));
export const useMoveThread = () => useThreadCommand((input: MoveThread) => command("thread.move", input));
export const useSetStatus = () => useThreadCommand((input: { id: number; status: ThreadStatus }) => command("thread.setStatus", input));
export const useSetImportance = () => useThreadCommand((input: { id: number; importance: Importance }) => command("thread.setImportance", input));
export const useSetCategory = () => useThreadCommand((input: { id: number; category: string | null }) => command("thread.setCategory", input));

export function useRules() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["rules"], queryFn: () => query("rules.get", {}), enabled: ready });
}

export function useSaveRules() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (rules: RuleSet) => command("rules.save", rules),
    onSuccess: (rules) => client.setQueryData(["rules"], rules),
  });
}

export function useDrafts() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["drafts"], queryFn: () => query("drafts.list", {}), enabled: ready });
}

export function useSaveDraft() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: Draft) => command("drafts.save", draft),
    onSuccess: () => client.invalidateQueries({ queryKey: ["drafts"] }),
  });
}

export function useRemoveDraft() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => command("drafts.remove", { id }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["drafts"] }),
  });
}

export const useReplyDraft = () =>
  useMutation({ mutationFn: (input: { message_id: number; reply_all: boolean }) => query("mail.replyDraft", input) });

export function useSendMail() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (draft: Draft) => command("mail.send", { draft }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["drafts"] }),
  });
}

export function useSearch(input: SearchMail, enabled: boolean) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["search", input], queryFn: () => query("search.run", input), enabled: ready && enabled, staleTime: 0 });
}

export function useCategories() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["categories"], queryFn: () => query("categories.list", {}), enabled: ready });
}

function useCategoryCommand<I, R>(run: (input: I) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    // The answer is the new list, and an event brings it to every other window too.
    onSuccess: (result) => {
      client.setQueryData(["categories"], { categories: (result as { categories: unknown }).categories });
      void client.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export const useSaveCategory = () => useCategoryCommand((input: SaveCategory) => command("categories.save", input));
export const useUpdateCategory = () => useCategoryCommand((input: UpdateCategory) => command("categories.update", input));
export const useReorderCategories = () => useCategoryCommand((names: string[]) => command("categories.reorder", { names }));
export const useRemoveCategory = () => useCategoryCommand((name: string) => command("categories.remove", { name }));
export const useDecidePriority = () => useCategoryCommand((input: { name: string; accept: boolean }) => command("categories.decidePriority", input));
export const useDecideCategory = () => useCategoryCommand((input: { name: string; accept: boolean }) => command("categories.decide", input));

export function useMailPresets() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-presets"], queryFn: () => query("mail.presets", {}), enabled: ready, staleTime: Infinity });
}

/** From only a server name, the likely ports and sending server. */
export const useProbeServer = () => useMutation({ mutationFn: (server: string) => command("mail.accounts.probe", { server }) });
