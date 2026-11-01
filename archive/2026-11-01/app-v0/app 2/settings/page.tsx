"use client";

import { Check, Moon, Palette, ShieldCheck, SlidersHorizontal, Sun } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useNexusStore } from "@/lib/store";
import type { ThemeName } from "@/lib/types";
import { cn } from "@/lib/utils";

const themeOptions: { id: ThemeName; title: string; description: string }[] = [
  {
    id: "terminal",
    title: "Terminal",
    description: "Hallmark terminal mode: mono everywhere, phosphor accent, dark system-console feel."
  },
  {
    id: "editorial",
    title: "Editorial",
    description: "Hallmark-inspired light OS with warm paper, sharp rules, and scarce coral accent."
  },
  {
    id: "mintlify",
    title: "Mintlify",
    description: "Clean AI-docs surfaces, mint accent, strong light and dark modes."
  },
  {
    id: "linear",
    title: "Linear",
    description: "Strict charcoal surfaces with scarce lavender accent."
  },
  {
    id: "nexus",
    title: "Nexus",
    description: "Deep navy surfaces with sharper AI workspace contrast."
  },
  {
    id: "graphite",
    title: "Graphite",
    description: "Neutral monochrome enterprise mode with warmer accent."
  }
];

function SettingRow({
  icon: Icon,
  title,
  description,
  enabled
}: {
  icon: typeof Palette;
  title: string;
  description: string;
  enabled: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-md rounded-lg border border-hairline bg-surface-1 p-md">
      <div className="flex min-w-0 items-start gap-sm">
        <div className="grid size-2xl shrink-0 place-items-center rounded-lg border border-hairline bg-surface-2">
          <Icon className="size-md text-accent" />
        </div>
        <div className="min-w-0">
          <p className="text-small text-ink">{title}</p>
          <p className="mt-xxs text-caption text-ink-subtle">{description}</p>
        </div>
      </div>
      <Button variant={enabled ? "primary" : "secondary"} size="sm">
        {enabled ? "On" : "Off"}
      </Button>
    </div>
  );
}

export default function SettingsPage() {
  const theme = useNexusStore((state) => state.theme);
  const setTheme = useNexusStore((state) => state.setTheme);
  const mode = useNexusStore((state) => state.mode);
  const setMode = useNexusStore((state) => state.setMode);

  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="Tune the workspace feel."
        description="Theme presets are token-driven, so the same UI can be tested across different enterprise AI moods."
      />
      <div className="mx-auto max-w-page space-y-lg px-xl py-xl">
        <Card className="p-lg">
          <div className="mb-lg flex items-center justify-between gap-md">
            <div>
              <div className="mb-xs flex items-center gap-xs text-caption text-accent">
                <Palette className="size-sm" />
                Theme system
              </div>
              <h2 className="text-heading text-ink">Visual presets</h2>
              <p className="mt-xxs text-small text-ink-subtle">
                Components use semantic variables, not component-level color values.
              </p>
            </div>
            <Badge variant="running">Token based</Badge>
          </div>
          <div className="grid gap-md lg:grid-cols-3 xl:grid-cols-6">
            {themeOptions.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setTheme(option.id)}
                className={cn(
                  "rounded-xl border border-hairline bg-surface-1 p-md text-left transition duration-200 ease-product hover:border-hairline-strong hover:bg-surface-2",
                  theme === option.id && "border-accent shadow-focus"
                )}
              >
                <div className="mb-md flex items-center justify-between gap-md">
                  <span className="text-heading text-ink">{option.title}</span>
                  {theme === option.id ? (
                    <span className="grid size-lg place-items-center rounded-full bg-accent text-ink-inverse">
                      <Check className="size-sm" />
                    </span>
                  ) : null}
                </div>
                <div className="mb-md grid grid-cols-4 gap-xxs">
                  <span className="h-md rounded-sm bg-canvas" />
                  <span className="h-md rounded-sm bg-surface-1" />
                  <span className="h-md rounded-sm bg-surface-3" />
                  <span className="h-md rounded-sm bg-accent" />
                </div>
                <p className="text-small text-ink-subtle">{option.description}</p>
              </button>
            ))}
          </div>
        </Card>

        <Card className="p-lg">
          <div className="mb-lg">
            <div className="mb-xs flex items-center gap-xs text-caption text-accent">
              <Sun className="size-sm" />
              Appearance mode
            </div>
            <h2 className="text-heading text-ink">Light and dark theme</h2>
            <p className="mt-xxs text-small text-ink-subtle">
              Both modes use the same semantic tokens so panels, email cards, and chat stay visually coherent.
            </p>
          </div>
          <div className="grid gap-md lg:grid-cols-2">
            {[
              { id: "dark" as const, title: "Dark OS", icon: Moon, description: "Premium low-light workspace for long sessions." },
              { id: "light" as const, title: "Light OS", icon: Sun, description: "Mintlify-style clean reading mode for demos and review." }
            ].map((option) => {
              const Icon = option.icon;
              const active = mode === option.id;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setMode(option.id)}
                  className={cn(
                    "rounded-xl border border-hairline bg-surface-1 p-md text-left transition duration-200 hover:border-hairline-strong hover:bg-surface-2",
                    active && "border-accent shadow-focus"
                  )}
                >
                  <div className="mb-sm flex items-center justify-between">
                    <span className="flex items-center gap-xs text-heading text-ink">
                      <Icon className="size-md text-accent" />
                      {option.title}
                    </span>
                    {active ? <Check className="size-md text-accent" /> : null}
                  </div>
                  <p className="text-small text-ink-subtle">{option.description}</p>
                </button>
              );
            })}
          </div>
        </Card>

        <div className="grid gap-md lg:grid-cols-2">
          <SettingRow
            icon={Moon}
            title="Mode-aware surfaces"
            description="Every card, panel, badge, and chat surface reads from semantic theme variables."
            enabled
          />
          <SettingRow
            icon={ShieldCheck}
            title="Enterprise privacy labels"
            description="Show source visibility and workspace boundaries on generated answers."
            enabled
          />
          <SettingRow
            icon={SlidersHorizontal}
            title="Glass density"
            description="Use subtle translucent panels over the surface ladder."
            enabled
          />
          <SettingRow
            icon={Palette}
            title="Experimental accent mixing"
            description="Keep accent usage scarce for a Linear-like product feel."
            enabled={false}
          />
        </div>
      </div>
    </>
  );
}
