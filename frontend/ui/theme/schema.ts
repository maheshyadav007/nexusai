import { z } from "zod";

const hex = z.string().regex(/^#[0-9A-Fa-f]{6}$/);
const size = z.string().regex(/^\d+(\.\d+)?(px|rem)$/);
const scale = z.number().positive();

export const themeSchema = z
  .object({
    id: z.string().regex(/^[a-z0-9-]+$/),
    name: z.string().min(1),
    mode: z.enum(["light", "dark"]),
    color: z.strictObject({
      surface: z.strictObject({ page: hex, raised: hex, sunken: hex, inverse: hex }),
      ink: z.strictObject({ primary: hex, secondary: hex, muted: hex, faint: hex, inverse: hex }),
      accent: z.strictObject({ default: hex, hover: hex, bright: hex, on: hex }),
      status: z.strictObject({ success: hex, warning: hex, danger: hex }),
      agent: z.strictObject({ running: hex, waiting: hex, done: hex, failed: hex }),
      line: z.strictObject({ subtle: hex, strong: hex }),
    }),
    type: z.strictObject({
      minSize: size,
      size: z.strictObject({ xs: size, sm: size, md: size, lg: size, xl: size, display: size }),
      family: z.strictObject({ sans: z.string(), serif: z.string(), mono: z.string() }),
    }),
    space: z.record(z.string(), size),
    radius: z.strictObject({ sm: size, md: size, lg: size, full: size }),
    shadow: z.strictObject({ raised: z.string(), overlay: z.string() }),
    motion: z.strictObject({ fast: z.string(), normal: z.string() }),
    layout: z.strictObject({ content: size }),
    scale: z.strictObject({
      density: z.strictObject({ compact: scale, comfortable: scale, spacious: scale }),
      text: z.strictObject({ small: scale, medium: scale, large: scale }),
    }),
  })
  .strict();

export type Theme = z.infer<typeof themeSchema>;

/** Text and background pairs that must stay readable in every theme. */
export const CONTRAST_PAIRS = [
  ["ink.primary", "surface.page"],
  ["ink.secondary", "surface.page"],
  ["ink.muted", "surface.page"],
  ["ink.primary", "surface.raised"],
  ["ink.secondary", "surface.raised"],
  ["ink.muted", "surface.raised"],
  ["ink.muted", "surface.sunken"],
  ["accent.default", "surface.page"],
  ["accent.on", "accent.default"],
  ["status.success", "surface.page"],
  ["status.warning", "surface.page"],
  ["status.danger", "surface.page"],
  ["ink.inverse", "surface.inverse"],
] as const;

export const MIN_CONTRAST = 4.5;

function luminance(color: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(color.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) =>
    c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  ) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

function colorAt(theme: Theme, path: string): string {
  const [group, name] = path.split(".") as [keyof Theme["color"], string];
  return (theme.color[group] as Record<string, string>)[name] as string;
}

export function contrastFailures(theme: Theme): string[] {
  return CONTRAST_PAIRS.flatMap(([text, background]) => {
    const ratio = contrast(colorAt(theme, text), colorAt(theme, background));
    return ratio < MIN_CONTRAST
      ? [`${theme.id}: ${text} on ${background} is ${ratio.toFixed(2)}:1, needs ${MIN_CONTRAST}:1`]
      : [];
  });
}
