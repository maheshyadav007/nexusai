"use client";

import { useEffect } from "react";
import { useNexusStore } from "@/lib/store";

export function ThemeProvider() {
  const theme = useNexusStore((state) => state.theme);
  const mode = useNexusStore((state) => state.mode);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.mode = mode;
  }, [mode, theme]);

  return null;
}
