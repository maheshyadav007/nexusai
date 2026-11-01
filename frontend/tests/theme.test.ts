import { execFileSync, spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { themeToCss } from "../ui/theme/css";
import { loadThemes } from "../ui/theme/generate";
import { contrastFailures, themeSchema } from "../ui/theme/schema";

const themes = loadThemes();
const light = themes.find((theme) => theme.id === "nexus-light")!;

describe("themes", () => {
  it("includes light and dark", () => {
    expect(themes.map((theme) => theme.mode).sort()).toEqual(["dark", "light"]);
  });

  it("all meet contrast targets", () => {
    expect(themes.flatMap(contrastFailures)).toEqual([]);
  });

  it("rejects a theme missing a token", () => {
    const { color, ...rest } = light;
    const { line: _line, ...partial } = color;
    expect(themeSchema.safeParse({ ...rest, color: partial }).success).toBe(false);
  });

  it("flags unreadable text", () => {
    const faint = { ...light, color: { ...light.color, ink: { ...light.color.ink, muted: "#E9CDBF" } } };
    expect(contrastFailures(faint).join()).toContain("ink.muted on surface.page");
  });

  it("the default theme cannot override a selected theme", () => {
    // Regression: a plain :root selector came later in the file and beat dark mode.
    expect(themeToCss(light, true)).toContain(':where(:root), [data-theme="nexus-light"]');
    expect(themeToCss(light, false)).not.toContain(":root");
  });

  it("changing one value in a theme file changes the CSS", () => {
    const changed = { ...light, color: { ...light.color, surface: { ...light.color.surface, page: "#102030" } } };
    expect(themeToCss(light, true)).toContain("--color-surface-page: 248 234 226;");
    expect(themeToCss(changed, true)).toContain("--color-surface-page: 16 32 48;");
  });
});

describe("no-hardcode check", () => {
  const run = (...paths: string[]) => spawnSync("node", ["scripts/check-no-hardcode.mjs", ...paths], { encoding: "utf8" });

  it("fails on hardcoded values, and names each one", () => {
    const result = run("tests/fixtures/hardcoded");
    expect(result.status).toBe(1);
    for (const problem of ["hardcoded color", "arbitrary Tailwind", "inline style", "text in JSX", "text in title"]) {
      expect(result.stderr).toContain(problem);
    }
  });

  it("passes on the app itself", () => {
    expect(() => execFileSync("node", ["scripts/check-no-hardcode.mjs", "ui", "app"], { encoding: "utf8" })).not.toThrow();
  });
});
