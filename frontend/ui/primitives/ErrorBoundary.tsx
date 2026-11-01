"use client";

import { Component, type ReactNode } from "react";
import { t } from "@/ui/strings";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="rounded-md border border-status-danger p-4 text-sm text-status-danger">
        <p>{t("error.title")}</p>
        <button type="button" className="mt-2 underline" onClick={() => this.setState({ failed: false })}>
          {t("error.retry")}
        </button>
      </div>
    );
  }
}
