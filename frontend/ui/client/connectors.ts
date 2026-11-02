"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { command, query } from "./api";
import type { AddConnector, Connectors, SetConnectorEnabled, TestConnector } from "./contracts.generated";
import { useHomeReady } from "./home";

export function useConnectors() {
  const ready = useHomeReady();
  return useQuery({ queryKey: ["connectors"], queryFn: () => query("connectors.list", {}), enabled: ready });
}

function useConnectorCommand<T>(run: (input: T) => Promise<Connectors>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: (connectors) => client.setQueryData(["connectors"], connectors) });
}

export const useTestConnector = () => useMutation({ mutationFn: (input: TestConnector) => command("connectors.test", input) });
export const useAddConnector = () => useConnectorCommand((input: AddConnector) => command("connectors.add", input));
export const useRefreshConnector = () => useConnectorCommand((id: string) => command("connectors.refresh", { id }));
export const useApproveConnector = () => useConnectorCommand((id: string) => command("connectors.approve", { id }));
export const useRemoveConnector = () => useConnectorCommand((id: string) => command("connectors.remove", { id }));
export const useSetConnectorEnabled = () => useConnectorCommand((input: SetConnectorEnabled) => command("connectors.setEnabled", input));
