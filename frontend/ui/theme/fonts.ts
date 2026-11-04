import { Instrument_Sans, Instrument_Serif, Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import type { FontId } from "./font-catalog";

// next/font downloads these at build time and serves them locally,
// so the app never calls Google Fonts at runtime (corporate proxies).
// Each variable must be --font-<catalog id>, because themes resolve fonts by that name.
// preload: false keeps a font no default theme uses from slowing the first paint.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const instrumentSans = Instrument_Sans({ subsets: ["latin"], variable: "--font-instrument-sans" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk" });
const instrumentSerif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-instrument-serif" });
const jetBrainsMono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-jetbrains-mono" });

const loaded: Record<FontId, { variable: string }> = {
  "inter": inter,
  "instrument-sans": instrumentSans,
  "space-grotesk": spaceGrotesk,
  "instrument-serif": instrumentSerif,
  "jetbrains-mono": jetBrainsMono,
};

export const fontVariables = Object.values(loaded)
  .map((font) => font.variable)
  .join(" ");
