"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { CreateSession, DecideApproval, Permissions } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useSessions(search: string) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["sessions", search], queryFn: () => query("sessions.list", { query: search }), enabled: ready });
}

export function useSession(id: string) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["session", id], queryFn: () => query("session.get", { id }), enabled: ready });
}

function useSessionCommand<T, R>(run: (input: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["sessions"] });
      void client.invalidateQueries({ queryKey: ["session"] });
    },
  });
}

// Kept in memory, because a link would put what the person typed in their browser history.
const firstMessages = new Map<string, string>();

/** The session screen sends this when it opens. */
export const leaveFirstMessage = (id: string, text: string) => void firstMessages.set(id, text);

export function takeFirstMessage(id: string): string | undefined {
  const text = firstMessages.get(id);
  firstMessages.delete(id);
  return text;
}

export const useCreateSession = () => useSessionCommand((input: CreateSession) => command("session.create", input));
export const useAnswerSession = () => useSessionCommand((input: { id: string; answer: string }) => command("session.answer", input));
export const useStopSession = () => useSessionCommand((id: string) => command("session.stop", { id }));
export const useRenameSession = () => useSessionCommand((input: { id: string; title: string }) => command("session.rename", input));
export const useArchiveSession = () => useSessionCommand((id: string) => command("session.archive", { id }));

export function useApprovals() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["approvals"], queryFn: () => query("approvals.list", {}), enabled: ready });
}

export function useDecideApproval() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: DecideApproval) => command("approvals.decide", input),
    onSuccess: () => client.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

export function useModelCall(session: string, enabled: boolean) {
  return useQuery({ queryKey: ["model-call", session], queryFn: () => query("modelCall.get", { session }), enabled, staleTime: 0 });
}

export function usePermissions() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["permissions"], queryFn: () => query("permissions.get", {}), enabled: ready });
}

export function useSavePermissions() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (permissions: Permissions) => command("permissions.save", permissions),
    onSuccess: (permissions) => {
      client.setQueryData(["permissions"], permissions);
      void client.invalidateQueries({ queryKey: ["permissions", "catalog"] });
    },
  });
}
