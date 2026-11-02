// Dependencies run one way: features → shell → primitives → theme. Fails on anything importing upward.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join } from "node:path";

const RULES = {
  theme: ["primitives", "shell", "features", "gallery"],
  primitives: ["shell", "features", "gallery", "client"],
  shell: ["features", "gallery"],
  features: ["gallery"],
};

function* files(path) {
  if (statSync(path).isDirectory()) {
    for (const entry of readdirSync(path)) if (entry !== "generated") yield* files(join(path, entry));
  } else if ([".ts", ".tsx"].includes(extname(path))) yield path;
}

const problems = [];
for (const root of process.argv.slice(2)) {
  for (const path of files(root)) {
    const layer = Object.keys(RULES).find((name) => path.split(/[\\/]/).includes(name));
    if (!layer) continue;
    const text = readFileSync(path, "utf8");
    for (const [, target] of text.matchAll(/from "(?:@\/ui\/|\.\.\/)([a-z]+)\//g)) {
      if (RULES[layer].includes(target)) problems.push(`${path}  ${layer} must not import ${target}`);
    }
  }
}
if (problems.length) {
  console.error(`Module boundaries broken:\n${problems.join("\n")}`);
  process.exit(1);
}
