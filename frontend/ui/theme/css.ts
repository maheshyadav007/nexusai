import type { Theme } from "./schema";

function channels(color: string): string {
  return [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)).join(" ");
}

export function themeToCss(theme: Theme, isDefault: boolean): string {
  const lines: string[] = [`color-scheme: ${theme.mode};`];
  for (const [group, values] of Object.entries(theme.color)) {
    for (const [name, value] of Object.entries(values)) {
      lines.push(`--color-${group}-${name}: ${channels(value)};`);
    }
  }
  for (const [name, value] of Object.entries(theme.type.size)) {
    lines.push(`--type-size-${name}: max(${theme.type.minSize}, calc(${value} * var(--text-scale)));`);
  }
  for (const [name, value] of Object.entries(theme.type.family)) lines.push(`--type-family-${name}: var(--font-${value});`);
  for (const [name, value] of Object.entries(theme.space)) lines.push(`--space-${name}: calc(${value} * var(--density-scale));`);
  for (const [name, value] of Object.entries(theme.radius)) lines.push(`--radius-${name}: ${value};`);
  for (const [name, value] of Object.entries(theme.shadow)) lines.push(`--shadow-${name}: ${value};`);
  for (const [name, value] of Object.entries(theme.motion)) lines.push(`--motion-${name}: ${value};`);
  for (const [name, value] of Object.entries(theme.layout)) lines.push(`--layout-${name}: ${value};`);
  lines.push(`--icon-stroke: ${theme.icon.stroke};`);
  // :where() has no specificity, so the default never overrides a selected theme.
  const selector = `${isDefault ? ":where(:root), " : ""}[data-theme="${theme.id}"]`;
  const body = lines.map((line) => `  ${line}`).join("\n");
  const scales = [
    ...Object.entries(theme.scale.density).map(([k, v]) => `${selector.split(", ").map((s) => `${s}[data-density="${k}"]`).join(", ")} { --density-scale: ${v}; }`),
    ...Object.entries(theme.scale.text).map(([k, v]) => `${selector.split(", ").map((s) => `${s}[data-text-size="${k}"]`).join(", ")} { --text-scale: ${v}; }`),
  ];
  return `${selector} {\n  --density-scale: 1;\n  --text-scale: 1;\n${body}\n}\n${scales.join("\n")}\n`;
}
