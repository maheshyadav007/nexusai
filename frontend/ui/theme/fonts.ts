import { Instrument_Serif, JetBrains_Mono, Space_Grotesk } from "next/font/google";

// next/font downloads these at build time and serves them locally,
// so the app never calls Google Fonts at runtime (corporate proxies).
const sans = Space_Grotesk({ subsets: ["latin"], variable: "--font-sans" });
const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-serif" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const fontVariables = `${sans.variable} ${serif.variable} ${mono.variable}`;
