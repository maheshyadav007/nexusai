"use client";

import { MotionConfig } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import appConfig from "@/app.config.json";
import { useSettings } from "@/ui/client/settings";

/** Applies saved appearance to the page. Components only ever see CSS variables. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { data } = useSettings();
  const followsSystem = data?.theme === "system";
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    if (!followsSystem) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => setSystemDark(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, [followsSystem]);

  useEffect(() => {
    if (!data) return;
    const theme = data.theme === "system" ? appConfig.systemThemes[systemDark ? "dark" : "light"] : data.theme;
    const attributes = { theme, density: data.density, "text-size": data.text_size, accent: data.accent };
    for (const [name, value] of Object.entries(attributes)) {
      document.documentElement.setAttribute(`data-${name}`, value);
    }
    try {
      localStorage.setItem(appConfig.storageKeys.appearance, JSON.stringify(attributes));
    } catch {
      // Storage can be blocked; the theme still applies once settings load.
    }
  }, [data, systemDark]);

  // Honors the system's reduced motion setting everywhere Motion is used.
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

/** Runs before first paint, so a saved theme never flashes the default. */
export const applySavedAppearance = `try{var a=JSON.parse(localStorage.getItem(${JSON.stringify(appConfig.storageKeys.appearance)}));for(var k in a)document.documentElement.setAttribute("data-"+k,a[k])}catch(e){}`;
