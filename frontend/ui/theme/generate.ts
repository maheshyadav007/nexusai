import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import appConfig from "../../app.config.json" with { type: "json" };
import { themeToCss } from "./css";
import { contrastFailures, themeSchema, type Theme } from "./schema";

const here = dirname(fileURLToPath(import.meta.url));
const themesDir = join(here, "themes");
const outDir = join(here, "generated");

export function loadThemes(dir = themesDir): Theme[] {
  return readdirSync(dir)
    .filter((file) => file.endsWith(".json"))
    .sort()
    .map((file) => themeSchema.parse(JSON.parse(readFileSync(join(dir, file), "utf8"))));
}

function main(): void {
  const themes = loadThemes();
  const failures = themes.flatMap(contrastFailures);
  if (failures.length) {
    console.error(`Theme contrast check failed:\n${failures.join("\n")}`);
    process.exit(1);
  }
  mkdirSync(outDir, { recursive: true });
  const css = themes.map((t) => themeToCss(t, t.id === appConfig.defaultTheme)).join("\n");
  writeFileSync(join(outDir, "themes.css"), css);
  const list = themes.map(({ id, name, mode }) => ({ id, name, mode }));
  writeFileSync(join(outDir, "theme-list.ts"), `export const THEMES = ${JSON.stringify(list, null, 2)} as const;\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
