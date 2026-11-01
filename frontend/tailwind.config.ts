import type { Config } from "tailwindcss";
import light from "./ui/theme/themes/nexus-light.json";

// Maps Tailwind names to CSS variables. Values live only in ui/theme/themes.
// Replacing these scales removes Tailwind's defaults, so only theme tokens can be used.
const vars = (prefix: string, values: object) =>
  Object.fromEntries(Object.keys(values).map((key) => [key, `var(--${prefix}-${key})`]));
const kebab = (key: string) => key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
const layout = Object.fromEntries(Object.keys(light.layout).map((key) => [kebab(key), `var(--layout-${key})`]));

const colors = Object.fromEntries(
  Object.entries(light.color).map(([group, values]) => [
    group,
    Object.fromEntries(
      Object.keys(values).map((name) => [name, `rgb(var(--color-${group}-${name}) / <alpha-value>)`]),
    ),
  ]),
);

// The easing curve is one value, not a duration.
const { easing: _easing, ...durations } = light.motion;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./ui/**/*.{ts,tsx}"],
  theme: {
    colors: { ...colors, transparent: "transparent", current: "currentColor" },
    fontSize: vars("type-size", light.type.size),
    fontFamily: vars("type-family", light.type.family),
    spacing: { 0: "0", px: "1px", ...vars("space", light.space) },
    borderRadius: { none: "0", ...vars("radius", light.radius) },
    boxShadow: { none: "none", ...vars("shadow", light.shadow) },
    transitionDuration: vars("motion", durations),
    transitionTimingFunction: { DEFAULT: "var(--motion-easing)" },
    maxWidth: { none: "none", full: "100%", ...layout },
    extend: {
      width: layout,
      height: layout,
      maxHeight: layout,
      keyframes: {
        fade: { from: { opacity: "0" } },
        rise: { from: { opacity: "0", transform: "translateY(var(--space-2))" } },
      },
      animation: {
        fade: "fade var(--motion-normal) var(--motion-easing)",
        rise: "rise var(--motion-normal) var(--motion-easing)",
      },
    },
  },
  plugins: [],
};

export default config;
