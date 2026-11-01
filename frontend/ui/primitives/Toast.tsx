"use client";

import * as RadixToast from "@radix-ui/react-toast";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { t } from "@/ui/strings";
import { IconButton } from "./IconButton";

export interface ToastMessage {
  title: string;
  description?: string;
  tone?: "neutral" | "danger";
}

const ToastContext = createContext<(message: ToastMessage) => void>(() => {});

export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<(ToastMessage & { id: string })[]>([]);
  const show = useCallback((message: ToastMessage) => setToasts((current) => [...current, { ...message, id: crypto.randomUUID() }]), []);
  const value = useMemo(() => show, [show]);
  return (
    <ToastContext.Provider value={value}>
      <RadixToast.Provider label={t("common.notification")}>
        {children}
        {toasts.map((toast) => (
          <RadixToast.Root key={toast.id} onOpenChange={(open) => (open ? null : setToasts((current) => current.filter((item) => item.id !== toast.id)))} className="flex animate-rise items-start justify-between gap-3 rounded-md border border-line-subtle bg-surface-raised p-3 text-ink-primary shadow-overlay">
            <div>
              <RadixToast.Title className={`text-md font-medium ${toast.tone === "danger" ? "text-status-danger" : ""}`}>{toast.title}</RadixToast.Title>
              {toast.description ? <RadixToast.Description className="mt-1 text-sm text-ink-muted">{toast.description}</RadixToast.Description> : null}
            </div>
            <RadixToast.Close asChild>
              <IconButton icon="close" label={t("common.close")} tooltip={false} />
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className="fixed bottom-0 right-0 z-50 flex w-popover max-w-full flex-col gap-2 p-4 outline-none" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
}
