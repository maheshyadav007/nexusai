"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { Draft, ListThreads, MailProfile, MoveThread, RuleSet, SaveCategory, SearchMail, SetThreadStatus } from "./contracts.generated";
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
    mutationFn: (input: { name: string; profile: MailProfile; password?: string | null }) => command("mail.accounts.save", input),
    onSuccess: (accounts) => client.setQueryData(["mail-accounts"], accounts),
  });
}

export function useRemoveAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => command("mail.accounts.remove", { name }),
    onSuccess: (accounts) => client.setQueryData(["mail-accounts"], accounts),
  });
}

const PAGE_SIZE = 100;

export function useThreads(folder: FolderRole, category: string | null) {
  const ready = useHomeReady();
  return useInfiniteQuery({
    queryKey: ["threads", folder, category],
    queryFn: ({ pageParam }) => query("threads.list", { folder, category, before: pageParam, limit: PAGE_SIZE }),
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
export const useMoveThread = () => useThreadCommand((input: MoveThread) => command("thread.move", input));
export const useSetStatus = () => useThreadCommand((input: { id: number; status: ThreadStatus }) => command("thread.setStatus", input));
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
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["categories"] });
      void client.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export const useSaveCategory = () => useCategoryCommand((input: SaveCategory) => command("categories.save", input));
export const useRemoveCategory = () => useCategoryCommand((name: string) => command("categories.remove", { name }));
export const useDecideCategory = () => useCategoryCommand((input: { name: string; accept: boolean }) => command("categories.decide", input));
