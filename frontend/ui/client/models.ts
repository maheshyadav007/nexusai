"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { ModelStatus } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useModelStatus() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["models"], queryFn: () => query("models.status", {}), enabled: ready });
}

export function useAvailableModels(enabled: boolean) {
  return useQuery({ queryKey: ["models-available"], queryFn: () => query("models.list", {}), enabled });
}

function useStatusCommand<T>(run: (input: T) => Promise<ModelStatus>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (status) => client.setQueryData(["models"], status),
  });
}

export const useStartLogin = () => useStatusCommand(() => command("models.login.start", {}));
export const useCancelLogin = () => useStatusCommand(() => command("models.login.cancel", {}));
export const useDisconnect = () => useStatusCommand(() => command("models.disconnect", {}));
export const useSelectModel = () => useStatusCommand((model: string) => command("models.select", { model }));

export function useTestModel() {
  return useMutation({ mutationFn: (prompt: string) => command("models.test", { prompt }) });
}
