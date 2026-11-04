/**
 * The fonts a theme can choose from, by role. To add one, list it here and load it
 * in fonts.ts; the type check fails until both are done. Themes then name it by id.
 */
export const FONT_CATALOG = {
  sans: ["inter", "instrument-sans", "space-grotesk"],
  serif: ["instrument-serif", "space-grotesk"],
  mono: ["jetbrains-mono"],
} as const;

export type FontId = (typeof FONT_CATALOG)[keyof typeof FONT_CATALOG][number];
