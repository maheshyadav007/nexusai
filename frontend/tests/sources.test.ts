import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { documentSource, fileSource, fullHref, mailSource, pageNumber } from "../ui/features/sources/kinds";
import { loadThemes } from "../ui/theme/generate";

const ROOT = join(__dirname, "..");

function* files(path: string): Generator<string> {
  if (statSync(path).isDirectory()) {
    for (const entry of readdirSync(path)) if (entry !== "generated" && entry !== "node_modules") yield* files(join(path, entry));
  } else if (/\.tsx?$/.test(path)) yield path;
}

describe("sources", () => {
  it("open each kind on its own full page", () => {
    expect(fullHref(mailSource(42))).toBe("/mail/all/42");
    expect(fullHref(documentSource("m:45:2"))).toBe("/documents/view?key=m%3A45%3A2");
    expect(fullHref(fileSource("Work/plan.txt"))).toBe("/documents/view?path=Work%2Fplan.txt");
  });

  it("read the page out of a citation", () => {
    expect(pageNumber("p3")).toBe(3);
    expect(pageNumber("page=12")).toBe(12);
    expect(pageNumber(null)).toBeNull();
    expect(pageNumber("intro")).toBeNull();
  });

  it("open over the chat, with menus and tooltips over both", () => {
    for (const theme of loadThemes()) {
      const layer = Object.fromEntries(Object.entries(theme.layer).map(([name, value]) => [name, Number(value)]));
      expect(layer.dialog).toBeGreaterThan(layer.dock!);
      expect(layer.float).toBeGreaterThan(layer.dialog!);
    }
  });
});

// Links to an email go through the sources registry, so they all open the same quick preview.
// Mail's own screens link to their threads, and the old address only redirects.
const MAY_LINK = [/^ui\/features\/sources\//, /^ui\/features\/mail\//, /^app\/\(app\)\/mail\//];

describe("links to mail", () => {
  it("go through the sources registry", () => {
    const direct = [...files(join(ROOT, "ui")), ...files(join(ROOT, "app"))]
      // Forward slashes on every system, so the rules read the same on Windows.
      .map((path) => relative(ROOT, path).split(sep).join("/"))
      .filter((path) => !MAY_LINK.some((rule) => rule.test(path)))
      .filter((path) => /\/mail\/(all|thread)\//.test(readFileSync(join(ROOT, path), "utf8")));
    expect(direct).toEqual([]);
  });
});
