// Fails on hardcoded colors, one-off sizes and user-facing text outside the files that own them.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative, sep } from "node:path";
import ts from "typescript";

const ALLOWED = ["ui/theme/", "ui/strings/", "ui/client/contracts.generated.ts"];
const COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|oklch)\(/;
const ARBITRARY = /(?:^|[\s"'`:])(?:[a-z-]+-)\[[^\]\s]+\]/;
const ALLOWED_ARBITRARY = /data-\[(?:state=[a-z]+|highlighted|disabled)\]:/g;
// From ui/DESIGN_DIRECTION.md: signs the audit removed, so they can't come back.
const BANNED = [
  [/\btransition-all\b/, "transition-all; name the properties"],
  [/\buppercase\b/, "uppercase label; use sentence case"],
  [/\bfont-(?:bold|extrabold|black)\b/, "heavy weight; use size and color for hierarchy"],
  [/\banimate-(?:pulse|ping|bounce)\b/, "looping animation; only real running work may move"],
  [/\bbg-gradient-|\b(?:from|via)-(?:surface|ink|accent|status|agent|line)\b/, "gradient; use a solid surface"],
  [/\bfont-serif\b.*\btabular-nums\b|\btabular-nums\b.*\bfont-serif\b/, "numbers in the serif; its 1 reads as l"],
];
const TEXT_ATTRIBUTES = new Set(["title", "placeholder", "alt", "aria-label", "label", "description"]);

function* files(path) {
  if (statSync(path).isDirectory()) {
    for (const entry of readdirSync(path)) {
      if (entry !== "node_modules" && entry !== ".next" && entry !== "generated") yield* files(join(path, entry));
    }
  } else if ([".ts", ".tsx", ".css"].includes(extname(path))) yield path;
}

function lineOf(text, index) {
  return text.slice(0, index).split("\n").length;
}

function scanText(path, text, report) {
  text.split("\n").forEach((line, i) => {
    if (COLOR.test(line)) report(path, i + 1, "hardcoded color; use a theme token");
    if (ARBITRARY.test(line.replace(ALLOWED_ARBITRARY, ""))) report(path, i + 1, "arbitrary Tailwind value; use a theme token");
    for (const [pattern, message] of BANNED) if (pattern.test(line)) report(path, i + 1, message);
  });
}

// Only primitives touch these, so replacing a component means editing one file.
const OUTSIDE_THE_DOOR = /^(?:ui\/(?:features|shell)|app)\//;
const DOOR_LIBRARIES = /^(?:motion\/react|@radix-ui\/|lucide-react|@\/ui\/primitives\/motionValues$)/;
const DOOR_ELEMENTS = new Set(["button", "input", "textarea", "select"]);

function scanJsx(path, text, report) {
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const outside = OUTSIDE_THE_DOOR.test(path.replaceAll("\\", "/"));
  const visit = (node) => {
    if (outside && ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) && DOOR_LIBRARIES.test(node.moduleSpecifier.text)) {
      report(path, lineOf(text, node.getStart()), `${node.moduleSpecifier.text} outside primitives; add what you need to ui/primitives`);
    }
    if (outside && (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && DOOR_ELEMENTS.has(node.tagName.getText())) {
      report(path, lineOf(text, node.getStart()), `raw <${node.tagName.getText()}>; use Pressable, BareInput or another primitive`);
    }
    if (ts.isJsxText(node) && /\p{L}/u.test(node.text)) {
      report(path, lineOf(text, node.getStart()), `text in JSX: "${node.text.trim()}"; use ui/strings`);
    }
    if (ts.isJsxAttribute(node) && node.initializer) {
      const name = node.name.getText();
      const value = ts.isStringLiteral(node.initializer) ? node.initializer.text : null;
      if (TEXT_ATTRIBUTES.has(name) && value && /\p{L}/u.test(value)) {
        report(path, lineOf(text, node.getStart()), `text in ${name}; use ui/strings`);
      }
      if (name === "style") report(path, lineOf(text, node.getStart()), "inline style; use theme tokens");
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
}

const problems = [];
const report = (path, line, message) => problems.push(`${path}:${line}  ${message}`);
for (const root of process.argv.slice(2)) {
  for (const path of files(root)) {
    const name = relative(process.cwd(), path).split(sep).join("/");
    if (ALLOWED.some((allowed) => name.startsWith(allowed))) continue;
    const text = readFileSync(path, "utf8");
    scanText(name, text, report);
    if (path.endsWith(".tsx")) scanJsx(name, text, report);
  }
}
// Agent names live only in the backend's agent files (the frontmatter of
// builtin_plugins/<plugin>/agents/<id>.md), so a rename is one change. Strings take them as {agent},
// filled from the cards the backend sends.
const PLUGINS = join(process.cwd(), "..", "backend", "src", "nexusai", "modules", "agent", "builtin_plugins");
const agentNames = readdirSync(PLUGINS, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .flatMap((plugin) => {
    const folder = join(PLUGINS, plugin.name, "agents");
    return existsSync(folder) ? readdirSync(folder).filter((entry) => entry.endsWith(".md")).map((entry) => join(folder, entry)) : [];
  })
  .map((path) => /^ {2}displayName: ['"]?(.+?)['"]?$/m.exec(readFileSync(path, "utf8").split("\n---\n")[0])?.[1])
  .filter(Boolean);
if (agentNames.length === 0) throw new Error(`No agent names found in ${PLUGINS}; the check would pass without checking.`);
const named = (text) => agentNames.find((agent) => new RegExp(`\\b${agent.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(text));
for (const [key, value] of Object.entries(JSON.parse(readFileSync("ui/strings/en.json", "utf8")))) {
  const agent = named(value);
  if (agent) report("ui/strings/en.json", key, `says "${agent}"; write {agent} and pass the name from its card`);
}
for (const root of process.argv.slice(2)) {
  for (const path of files(root)) {
    const name = relative(process.cwd(), path).split(sep).join("/");
    if (name.startsWith("ui/client/contracts.generated.ts")) continue;
    readFileSync(path, "utf8").split("\n").forEach((line, i) => {
      const agent = named(line);
      if (agent && !/^\s*(?:\/\/|\*|\/\*)/.test(line)) report(name, i + 1, `says "${agent}"; take agent names from their cards`);
    });
  }
}
if (problems.length) {
  console.error(`Hardcoded values found:\n${problems.join("\n")}`);
  process.exit(1);
}
