"use client";

import { useInfiniteQuery, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiRequestError, command, query } from "./api";
import type { ApiError, Importance, Draft, DraftAttachment, ListThreads, MailMe, MailProfile, MailRule, NotAboutMe, MoveThread, PreviewCategoryRule, RuleCondition, RuleSet, SaveCategory, SearchMail, SetThreadStatus, SplitFolders, UpdateCategory } from "./contracts.generated";
import { useHomeReady } from "./home";
import { askAboutRest } from "./rest";

export type FolderRole = NonNullable<ListThreads["folder"]>;
export type ThreadStatus = SetThreadStatus["status"];

export function useMailStatus() {
  const ready = useHomeReady();
  // Kept current by events: mail.syncProgress arrives about once a second while mail comes down.
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

function useThreadCommand<T, R = unknown>(run: (input: T) => Promise<R>) {
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
export const useToInbox = () => useThreadCommand((input: { id: number; always?: boolean }) => command("thread.toInbox", input));
export const useMoveThread = () => useThreadCommand((input: MoveThread) => command("thread.move", input));
export const useSetStatus = () =>
  useThreadCommand(async (input: { id: number; status: ThreadStatus }) => {
    const done = await command("thread.setStatus", input);
    // A conversation marked done asks about the rest of its matter, like a finished task.
    if (input.status === "resolved") askAboutRest(`thread:${input.id}`);
    return done;
  });
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

/** What a whole rule, with any and its exceptions, catches among the mail here: a count and a few. */
export function useWholeRulePreview(rule: MailRule | null) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["rules", "preview", rule], queryFn: () => query("rules.preview", { rule: rule as MailRule }), enabled: ready && rule !== null, placeholderData: (previous) => previous });
}

/** Who the person is, as people write it: what counts as naming them on mail the AI doesn't read. */
export function useMe() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["me"], queryFn: () => query("me.get", {}), enabled: ready });
}

export function useSaveMe() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (me: MailMe) => command("me.save", me),
    onSuccess: (me) => client.setQueryData(["me"], me),
  });
}

/** Where sorting stands: scoring, ready, done or skipped. The Sort page keeps it current. */
export function useMailSort(enabled = true) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-sort"], queryFn: () => query("mail.sort.get", {}), enabled: ready && enabled });
}

/** What a list of names would let through from hidden mail, before it's saved. */
export function useMePreview(names: readonly string[]) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["me", "preview", names], queryFn: () => query("me.preview", { names: [...names] }), enabled: ready, placeholderData: (previous) => previous });
}

export function useNamedYou() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["me", "named"], queryFn: () => query("me.named", {}), enabled: ready });
}

export function useNotAboutMe() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: NotAboutMe) => command("me.notAboutMe", input),
    onSuccess: (me) => {
      client.setQueryData(["me"], me);
      void client.invalidateQueries({ queryKey: ["me", "named"] });
      void client.invalidateQueries({ queryKey: ["threads"] });
      void client.invalidateQueries({ queryKey: ["thread"] });
    },
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

export const useForwardDraft = () => useMutation({ mutationFn: (input: { message_id: number }) => query("mail.forwardDraft", input) });

/** A file added in the composer. The app keeps it until the draft is sent or thrown away. */
export const useAttachFile = () =>
  useMutation({
    mutationFn: async (file: File): Promise<DraftAttachment> => {
      const response = await fetch(`/api/mail/draft-attachment?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
      if (!response.ok) throw new ApiRequestError((await response.json()) as ApiError);
      return (await response.json()) as DraftAttachment;
    },
  });

export function useRecipientSuggestions(text: string) {
  const ready = useHomeReady();
  const wanted = text.trim();
  return useQuery({ queryKey: ["recipient-suggestions", wanted], queryFn: () => query("mail.suggestRecipients", { text: wanted }), enabled: ready && wanted.length >= 2, staleTime: 30_000 });
}

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
      void client.invalidateQueries({ queryKey: ["mixed-folders"] });
      void client.invalidateQueries({ queryKey: ["rules"] });
    },
  });
}

export const useSaveCategory = () => useCategoryCommand((input: SaveCategory) => command("categories.save", input));
export const useUpdateCategory = () => useCategoryCommand((input: UpdateCategory) => command("categories.update", input));
export const useReorderCategories = () => useCategoryCommand((names: string[]) => command("categories.reorder", { names }));
export const useRemoveCategory = () => useCategoryCommand((name: string) => command("categories.remove", { name }));
export const useDecidePriority = () => useCategoryCommand((input: { name: string; accept: boolean }) => command("categories.decidePriority", input));
export const useDecideCategory = () => useCategoryCommand((input: { name: string; accept: boolean }) => command("categories.decide", input));
export const useSplitFolders = () => useCategoryCommand((input: SplitFolders) => command("categories.split", input));

/** Folders with senders on both sides, each waiting to be split once. */
export function useMixedFolders() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mixed-folders"], queryFn: () => query("categories.mixed", {}), enabled: ready });
}

/** How many conversations already here a rule would file, saving nothing. */
export function useRulePreview(conditions: readonly RuleCondition[]) {
  const ready = useHomeReady();
  const usable = conditions.filter((condition) => condition.field === "has_attachment" || (condition.value ?? "").trim());
  return useQuery({ queryKey: ["rule-preview", usable], queryFn: () => query("categories.preview", { conditions: usable as PreviewCategoryRule["conditions"] }), enabled: ready && usable.length > 0 });
}

export function useMailPresets() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["mail-presets"], queryFn: () => query("mail.presets", {}), enabled: ready, staleTime: Infinity });
}

/** From only a server name, the likely ports and sending server. */
export const useProbeServer = () => useMutation({ mutationFn: (server: string) => command("mail.accounts.probe", { server }) });
