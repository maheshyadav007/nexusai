"use client";

import { Component, type ReactNode } from "react";
import { t } from "@/ui/strings";
import { ErrorState } from "./ErrorState";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return <ErrorState title={t("error.title")} onRetry={() => this.setState({ failed: false })} />;
  }
}
