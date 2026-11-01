import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", '[data-mode="dark"]'],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        "canvas-elevated": "rgb(var(--canvas-elevated) / <alpha-value>)",
        surface: {
          1: "rgb(var(--surface-1) / <alpha-value>)",
          2: "rgb(var(--surface-2) / <alpha-value>)",
          3: "rgb(var(--surface-3) / <alpha-value>)",
          4: "rgb(var(--surface-4) / <alpha-value>)"
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          muted: "rgb(var(--ink-muted) / <alpha-value>)",
          subtle: "rgb(var(--ink-subtle) / <alpha-value>)",
          tertiary: "rgb(var(--ink-tertiary) / <alpha-value>)",
          inverse: "rgb(var(--ink-inverse) / <alpha-value>)"
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          focus: "rgb(var(--accent-focus) / <alpha-value>)",
          soft: "rgb(var(--accent-soft) / <alpha-value>)"
        },
        hairline: {
          DEFAULT: "rgb(var(--hairline) / <alpha-value>)",
          strong: "rgb(var(--hairline-strong) / <alpha-value>)",
          faint: "rgb(var(--hairline-faint) / <alpha-value>)"
        },
        status: {
          success: "rgb(var(--status-success) / <alpha-value>)",
          warning: "rgb(var(--status-warning) / <alpha-value>)",
          danger: "rgb(var(--status-danger) / <alpha-value>)",
          info: "rgb(var(--status-info) / <alpha-value>)"
        }
      },
      fontFamily: {
        sans: "var(--font-sans)",
        mono: "var(--font-mono)"
      },
      fontSize: {
        hero: [
          "var(--text-hero)",
          {
            lineHeight: "var(--leading-hero)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-display)"
          }
        ],
        title: [
          "var(--text-title)",
          {
            lineHeight: "var(--leading-title)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-display)"
          }
        ],
        heading: [
          "var(--text-heading)",
          {
            lineHeight: "var(--leading-heading)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-heading)"
          }
        ],
        subhead: [
          "var(--text-subhead)",
          {
            lineHeight: "var(--leading-subhead)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-body)"
          }
        ],
        body: [
          "var(--text-body)",
          {
            lineHeight: "var(--leading-body)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-body)"
          }
        ],
        small: [
          "var(--text-small)",
          {
            lineHeight: "var(--leading-small)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-body)"
          }
        ],
        caption: [
          "var(--text-caption)",
          {
            lineHeight: "var(--leading-caption)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-body)"
          }
        ],
        button: [
          "var(--text-button)",
          {
            lineHeight: "var(--leading-button)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-button)"
          }
        ],
        mono: [
          "var(--text-mono)",
          {
            lineHeight: "var(--leading-mono)",
            letterSpacing: "var(--tracking-flat)",
            fontWeight: "var(--weight-body)"
          }
        ]
      },
      borderRadius: {
        xs: "var(--radius-xs)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-2xl)",
        full: "var(--radius-full)"
      },
      spacing: {
        xxs: "var(--space-xxs)",
        xs: "var(--space-xs)",
        sm: "var(--space-sm)",
        md: "var(--space-md)",
        lg: "var(--space-lg)",
        xl: "var(--space-xl)",
        "2xl": "var(--space-2xl)",
        "3xl": "var(--space-3xl)",
        section: "var(--space-section)",
        sidebar: "var(--layout-sidebar)",
        intelligence: "var(--layout-intelligence)",
        topbar: "var(--layout-topbar)",
        composer: "var(--layout-composer)"
      },
      maxWidth: {
        page: "var(--layout-page-max)",
        chat: "var(--layout-chat-max)",
        reading: "var(--layout-reading-max)"
      },
      boxShadow: {
        panel: "var(--shadow-panel)",
        lift: "var(--shadow-lift)",
        focus: "var(--shadow-focus)"
      },
      transitionTimingFunction: {
        product: "var(--ease-product)"
      }
    }
  },
  plugins: []
};

export default config;
