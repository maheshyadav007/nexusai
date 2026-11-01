import type { Config } from "tailwindcss";

// Tokens follow the v9 design reference: public/designs/NexusAI v9.dc.html
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F8EAE2",
        ink: {
          DEFAULT: "#191714",
          soft: "#4A423A",
          muted: "#8A7F73",
          faint: "#A79B8D"
        },
        accent: {
          DEFAULT: "#A8441F",
          bright: "#C0532E",
          deep: "#8E3717"
        },
        positive: {
          DEFAULT: "#4E7A43",
          deep: "#3B5C33"
        },
        warning: "#9A6A12",
        danger: "#A83226"
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Segoe UI Variable", "-apple-system", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "Consolas", "ui-monospace", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
