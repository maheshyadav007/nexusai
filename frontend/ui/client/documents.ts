"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiRequestError, command, query } from "./api";
import type { ApiError, DocumentRow, ListDocuments, Panel, PanelBoard, UpdateDocument } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useDocuments(input: ListDocuments) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["documents", input], queryFn: () => query("documents.list", input), enabled: ready });
}

export function useDocument(key: string | null) {
  return useQuery({ queryKey: ["document", key], queryFn: () => query("documents.get", { key: key ?? "" }), enabled: Boolean(key), staleTime: 0 });
}

function useDocumentCommand<T>(run: (input: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: () => client.invalidateQueries({ queryKey: ["documents"] }) });
}

export const useUpdateDocument = () => useDocumentCommand((input: UpdateDocument) => command("documents.update", input));
export const useRemoveDocument = () => useDocumentCommand((key: string) => command("documents.remove", { key }));
export const useSaveFolders = () => useDocumentCommand((folders: string[]) => command("documents.saveFolders", { folders }));

export const useUpload = () =>
  useDocumentCommand(async (file: File): Promise<DocumentRow> => {
    const response = await fetch(`/api/documents/upload?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    if (!response.ok) throw new ApiRequestError((await response.json()) as ApiError);
    return (await response.json()) as DocumentRow;
  });

export const documentUrl = (key: string) => `/api/documents/file?key=${encodeURIComponent(key)}`;

export function usePstImports() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["pst"], queryFn: () => query("pst.imports", {}), enabled: ready });
}

function usePstCommand<T>(run: (input: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: () => client.invalidateQueries({ queryKey: ["pst"] }) });
}

export const useAddPst = () => usePstCommand((path: string) => command("pst.add", { path }));
export const usePausePst = () => usePstCommand((id: number) => command("pst.pause", { id }));
export const useResumePst = () => usePstCommand((id: number) => command("pst.resume", { id }));

export function usePanelBoard() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["panels"], queryFn: () => query("panels.board", {}), enabled: ready });
}

export function useSaveBoard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (board: PanelBoard) => command("panels.saveBoard", board),
    // Shown at once, so a dragged panel doesn't jump back while saving.
    onMutate: (board) => client.setQueryData(["panels"], board),
  });
}

export function useResetBoard() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => command("panels.reset", {}),
    onSuccess: (board) => client.setQueryData(["panels"], board),
  });
}

export function usePanelResults(panel: Panel) {
  return useQuery({ queryKey: ["panel-results", panel], queryFn: () => query("panels.results", { panel }) });
}
