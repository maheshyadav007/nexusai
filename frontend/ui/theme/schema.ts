import { z } from "zod";
import { FONT_CATALOG } from "./font-catalog";

const hex = z.string().regex(/^#[0-9A-Fa-f]{6}$/);
const size = z.string().regex(/^\d+(\.\d+)?(px|rem)$/);
const scale = z.number().positive();
const accent = z.strictObject({ default: hex, hover: hex, bright: hex, on: hex });

export const themeSchema = z
  .object({
    id: z.string().regex(/^[a-z0-9-]+$/),
    name: z.string().min(1),
    mode: z.enum(["light", "dark"]),
    color: z.strictObject({
      surface: z.strictObject({ page: hex, raised: hex, sunken: hex, inverse: hex, scrim: hex }),
      ink: z.strictObject({ primary: hex, secondary: hex, muted: hex, faint: hex, inverse: hex }),
      accent: z.strictObject({ default: hex, hover: hex, bright: hex, on: hex }),
      status: z.strictObject({ success: hex, warning: hex, danger: hex }),
      agent: z.strictObject({ running: hex, waiting: hex, done: hex, failed: hex }),
      line: z.strictObject({ subtle: hex, strong: hex }),
      // The colors of anything the agents do for you, so AI looks the same everywhere.
      ai: z.strictObject({ one: hex, two: hex, three: hex, four: hex }),
    }),
    accents: z.strictObject({ terracotta: accent, cobalt: accent, moss: accent, plum: accent }),
    type: z.strictObject({
      minSize: size,
      size: z.strictObject({ xs: size, sm: size, md: size, lg: size, xl: size, display: size, hero: size }),
      family: z.strictObject({ sans: z.enum(FONT_CATALOG.sans), serif: z.enum(FONT_CATALOG.serif), mono: z.enum(FONT_CATALOG.mono) }),
    }),
    space: z.record(z.string(), size),
    radius: z.strictObject({ sm: size, md: size, lg: size, full: size }),
    shadow: z.strictObject({ raised: z.string(), overlay: z.string() }),
    motion: z.strictObject({ fast: z.string(), normal: z.string(), slow: z.string(), press: z.string(), easing: z.string() }),
    layout: z.strictObject({ content: size, page: size, sidebar: size, rail: size, railWide: size, dock: size, dockHeight: size, reading: size, mailList: size, topbar: size, popover: size, drawer: size, dialog: size, modal: size, modalHeight: size, aura: size }),
    glass: z.strictObject({ opacity: z.string(), blur: size }),
    icon: z.strictObject({ stroke: z.string() }),
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
  const failure = (text: string, background: string, a: string, b: string) => {
    const ratio = contrast(a, b);
    return ratio < MIN_CONTRAST ? [`${theme.id}: ${text} on ${background} is ${ratio.toFixed(2)}:1, needs ${MIN_CONTRAST}:1`] : [];
  };
  return [
    ...CONTRAST_PAIRS.flatMap(([text, background]) => failure(text, background, colorAt(theme, text), colorAt(theme, background))),
    ...Object.entries(theme.accents).flatMap(([name, values]) => [
      ...failure(`accents.${name}.default`, "surface.page", values.default, theme.color.surface.page),
      ...failure(`accents.${name}.default`, "surface.sunken", values.default, theme.color.surface.sunken),
      ...failure(`accents.${name}.on`, `accents.${name}.default`, values.on, values.default),
    ]),
  ];
}
