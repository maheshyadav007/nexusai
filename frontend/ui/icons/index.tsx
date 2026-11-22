import type { IconName, IconSet } from "./names";
import { ICONOIR } from "./sets/iconoir";

export type { IconName } from "./names";

// The one icon set the app draws with. To try another, add it under ./sets and change this line.
export const ICONS: IconSet = ICONOIR;

export function Icon({ name, className = "h-4 w-4 shrink-0" }: { name: IconName; className?: string }) {
  const Glyph = ICONS[name];
  return <Glyph aria-hidden className={`icon ${className}`} />;
}
