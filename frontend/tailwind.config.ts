import type { Config } from "tailwindcss";
import light from "./ui/theme/themes/nexus-light.json";

// Maps Tailwind names to CSS variables. Values live only in ui/theme/themes.
// Replacing these scales removes Tailwind's defaults, so only theme tokens can be used.
const vars = (prefix: string, values: object) =>
  Object.fromEntries(Object.keys(values).map((key) => [key, `var(--${prefix}-${key})`]));

const colors = Object.fromEntries(
  Object.entries(light.color).map(([group, values]) => [
    group,
    Object.fromEntries(
      Object.keys(values).map((name) => [name, `rgb(var(--color-${group}-${name}) / <alpha-value>)`]),
    ),
  ]),
);

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./ui/**/*.{ts,tsx}"],
  theme: {
    colors: { ...colors, transparent: "transparent", current: "currentColor" },
    fontSize: vars("type-size", light.type.size),
    fontFamily: vars("type-family", light.type.family),
    spacing: { 0: "0", px: "1px", ...vars("space", light.space) },
    borderRadius: { none: "0", ...vars("radius", light.radius) },
    boxShadow: { none: "none", ...vars("shadow", light.shadow) },
    transitionDuration: vars("motion", light.motion),
    maxWidth: { none: "none", full: "100%", ...vars("layout", light.layout) },
  },
  plugins: [],
};

export default config;
