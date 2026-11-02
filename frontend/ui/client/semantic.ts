"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { RebuildIndex, SaveSemanticSettings, SemanticStatus } from "./contracts.generated";
import { useHomeReady } from "./home";

const KEY = ["semantic"];

/** Stays current through semantic.changed, which carries the whole status. */
export function useSemantic() {
  const ready = useHomeReady();
  return useQuery({ queryKey: KEY, queryFn: () => query("semantic.status", {}), enabled: ready });
}

function useSemanticCommand<T>(run: (input: T) => Promise<SemanticStatus>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: (status) => client.setQueryData(KEY, status) });
}

export const useDownloadModel = () => useSemanticCommand((id: string) => command("semantic.download", { id }));
export const useCancelModel = () => useSemanticCommand((id: string) => command("semantic.cancel", { id }));
export const useRemoveModel = () => useSemanticCommand((id: string) => command("semantic.remove", { id }));
export const useChooseModel = () => useSemanticCommand((id: string) => command("semantic.setActive", { id }));
export const useSaveSemantic = () => useSemanticCommand((changes: SaveSemanticSettings) => command("semantic.saveSettings", changes));
export const useRebuildIndex = () => useSemanticCommand((kind: RebuildIndex["kind"]) => command("semantic.rebuild", { kind }));
export const useDetectModels = () => useQuery({ queryKey: ["semantic-detect"], queryFn: () => query("semantic.detect", {}), staleTime: 0 });
export const useImportModel = () => useSemanticCommand((input: { id: string; folder: string }) => command("semantic.importFiles", input));
