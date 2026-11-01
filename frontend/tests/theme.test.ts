import { execFileSync, spawnSync } from "node:child_process";
import { ICONS } from "../ui/icons";
import { findNavItem, NAV_BOTTOM, NAV_SECTIONS, NAV_TOP } from "../ui/shell/nav";
import en from "../ui/strings/en.json";
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
    expect(themeToCss(light, true)).toContain("--color-surface-page: 247 244 238;");
    expect(themeToCss(changed, true)).toContain("--color-surface-page: 16 32 48;");
  });
});

describe("fonts", () => {
  it("a theme chooses its font by name, and the CSS follows", () => {
    const swapped = { ...light, type: { ...light.type, family: { ...light.type.family, sans: "space-grotesk" as const } } };
    expect(themeToCss(light, true)).toContain("--type-family-sans: var(--font-instrument-sans);");
    expect(themeToCss(swapped, true)).toContain("--type-family-sans: var(--font-space-grotesk);");
  });

  it("rejects a font that isn't in the catalog", () => {
    const unknown = { ...light, type: { ...light.type, family: { ...light.type.family, sans: "comic-sans" } } };
    expect(themeSchema.safeParse(unknown).success).toBe(false);
  });

  it("rejects a font used in the wrong role", () => {
    const wrong = { ...light, type: { ...light.type, family: { ...light.type.family, mono: "instrument-sans" } } };
    expect(themeSchema.safeParse(wrong).success).toBe(false);
  });
});

describe("navigation", () => {
  const items = [...NAV_TOP, ...NAV_SECTIONS.flatMap((section) => section.items), ...NAV_BOTTOM];

  it("every label, placeholder and icon exists", () => {
    for (const item of items) {
      expect(en).toHaveProperty([item.label]);
      if (item.arrives) expect(en).toHaveProperty([item.arrives]);
      expect(ICONS).toHaveProperty(item.icon);
    }
    for (const section of NAV_SECTIONS) expect(en).toHaveProperty([section.label]);
  });

  it("finds an item from its path, and not from a similar one", () => {
    expect(findNavItem("/mail/inbox")?.id).toBe("inbox");
    expect(findNavItem("/mail/inbox/123")?.id).toBe("inbox");
    expect(findNavItem("/mail/inboxes")).toBeUndefined();
  });
});

describe("boundaries check", () => {
  it("fails when a component imports upward", () => {
    const result = spawnSync("node", ["scripts/check-boundaries.mjs", "tests/fixtures/boundary"], { encoding: "utf8" });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("primitives must not import shell");
  });

  it("passes on the app itself", () => {
    expect(() => execFileSync("node", ["scripts/check-boundaries.mjs", "ui"], { encoding: "utf8" })).not.toThrow();
  });
});

describe("no-hardcode check", () => {
  const run = (...paths: string[]) => spawnSync("node", ["scripts/check-no-hardcode.mjs", ...paths], { encoding: "utf8" });

  it("fails on hardcoded values, and names each one", () => {
    const result = run("tests/fixtures/hardcoded");
    expect(result.status).toBe(1);
    for (const problem of ["hardcoded color", "arbitrary Tailwind", "inline style", "text in JSX", "text in title", "uppercase label", "transition-all"]) {
      expect(result.stderr).toContain(problem);
    }
  });

  it("passes on the app itself", () => {
    expect(() => execFileSync("node", ["scripts/check-no-hardcode.mjs", "ui", "app"], { encoding: "utf8" })).not.toThrow();
  });
});
