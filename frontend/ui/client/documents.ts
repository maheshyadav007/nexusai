"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiRequestError, command, query } from "./api";
import type { ApiError, DocumentRow, ListDocuments, Panel, PanelBoard, PstSearchStatus, PstUploadStatus, ReadDocument, UpdateDocument } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useDocuments(input: ListDocuments) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["documents", input], queryFn: () => query("documents.list", input), enabled: ready });
}

export function useDocument(key: string | null) {
  return useQuery({ queryKey: ["document", key], queryFn: () => query("documents.get", { key: key ?? "" }), enabled: Boolean(key), staleTime: 0 });
}

/** Which of these uploads aren't read yet. Events refresh them, the same as an open document. */
export function useReadingDocuments(keys: readonly string[]): ReadonlySet<string> {
  const results = useQueries({ queries: keys.map((key) => ({ queryKey: ["document", key], queryFn: () => query("documents.get", { key }), staleTime: 0 })) });
  return new Set(keys.filter((_, index) => results[index]?.data?.document.status === "pending"));
}

function useDocumentCommand<T, R>(run: (input: T) => Promise<R>) {
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

export const useReadAgain = () => useDocumentCommand((key: string) => command("documents.readAgain", { key }));

export function useHomeFolder(path: string) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["home-folder", path], queryFn: () => query("homeFiles.list", { path }), enabled: ready, staleTime: 0 });
}

export function useDocumentReader(input: ReadDocument) {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["document", "reader", input], queryFn: () => query("documents.read", input), enabled: ready && Boolean(input.key ?? input.path), staleTime: 0 });
}

export const documentUrl = (key: string) => `/api/documents/file?key=${encodeURIComponent(key)}`;

export function usePstImports() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["pst"], queryFn: () => query("pst.imports", {}), enabled: ready });
}

function usePstCommand<T>(run: (input: T) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: () => client.invalidateQueries({ queryKey: ["pst"] }) });
}

const UPLOAD_PIECE_BYTES = 8 * 1024 * 1024;
const UPLOAD_RETRIES = 5;
const UPLOAD_RETRY_MS = 1000;

/**
 * Sends a large file in pieces and returns where it landed. A dropped connection tries again from
 * where it stopped, and only something the backend refused ends it.
 */
export async function uploadPst(file: File, onProgress: (received: number) => void): Promise<string> {
  const started = await command("pst.uploadStart", { name: file.name, size: file.size, modified: file.lastModified });
  let received = started.received;
  let failures = 0;
  onProgress(received);
  for (;;) {
    try {
      const response = await fetch(`/api/pst/upload/${started.id}?offset=${received}`, { method: "POST", body: file.slice(received, received + UPLOAD_PIECE_BYTES) });
      if (!response.ok) throw new ApiRequestError((await response.json()) as ApiError);
      const status = (await response.json()) as PstUploadStatus;
      received = status.received;
      failures = 0;
      onProgress(received);
      if (status.path) return status.path;
    } catch (error) {
      failures += 1;
      if (error instanceof ApiRequestError || failures > UPLOAD_RETRIES) throw error;
      await new Promise((done) => setTimeout(done, UPLOAD_RETRY_MS * failures));
    }
  }
}

export function usePstSearch() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["pst-search"], queryFn: () => query("pst.search", {}), enabled: ready });
}

export const useFindPst = () => usePstSearchCommand((everywhere: boolean) => command("pst.find", { everywhere }));
export const useStopFindPst = () => usePstSearchCommand(() => command("pst.findStop", {}));

function usePstSearchCommand<T>(run: (input: T) => Promise<PstSearchStatus>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: (status) => client.setQueryData(["pst-search"], status) });
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
