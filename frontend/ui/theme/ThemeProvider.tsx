"use client";

import { useEffect, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import { useSettings } from "@/ui/client/settings";

/** Applies saved appearance to the page. Components only ever see CSS variables. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { data } = useSettings();

  useEffect(() => {
    if (!data) return;
    const attributes = { theme: data.theme, density: data.density, "text-size": data.text_size };
    for (const [name, value] of Object.entries(attributes)) {
      document.documentElement.setAttribute(`data-${name}`, value);
    }
    try {
      localStorage.setItem(appConfig.storageKeys.appearance, JSON.stringify(attributes));
    } catch {
      // Storage can be blocked; the theme still applies once settings load.
    }
  }, [data]);

  return children;
}

/** Runs before first paint, so a saved theme never flashes the default. */
export const applySavedAppearance = `try{var a=JSON.parse(localStorage.getItem(${JSON.stringify(appConfig.storageKeys.appearance)}));for(var k in a)document.documentElement.setAttribute("data-"+k,a[k])}catch(e){}`;
