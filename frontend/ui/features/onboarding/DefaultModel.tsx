"use client";

import { useEffect, useRef } from "react";
import { useAvailableModels, useModelStatus, useSelectModel } from "@/ui/client/models";

/** A configured provider needs no extra setup page merely to pick its first model. */
export function DefaultModel() {
  const status = useModelStatus();
  const needsDefault = Boolean(status.data?.connected && !status.data.selected_model);
  const offered = useAvailableModels(needsDefault);
  const select = useSelectModel();
  const attempted = useRef<string | null>(null);
  const first = offered.data?.models[0]?.id;
  useEffect(() => {
    if (!needsDefault || !first || attempted.current === first) return;
    attempted.current = first; select.mutate(first);
  }, [first, needsDefault, select]);
  return null;
}
