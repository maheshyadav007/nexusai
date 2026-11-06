/**
 * An agent's face, drawn from its card's seed so it's the same every time and changes only when
 * the seed does. Colors are the theme's AI colors. To use a different generator, replace this file.
 */

const BODY = ["fill-ai-one", "fill-ai-two", "fill-ai-three", "fill-ai-four"] as const;
const SIZE = { sm: "h-5 w-5", md: "h-8 w-8", lg: "h-guide w-guide" } as const;

/** FNV-1a, so the same seed always gives the same picture on every computer. */
function hash(seed: string): number {
  let value = 2166136261;
  for (const char of seed) {
    value ^= char.codePointAt(0) ?? 0;
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

function pick(value: number, shift: number, count: number): number {
  return (value >>> shift) % count;
}

function Body({ shape, className }: { shape: string; className: string }) {
  if (shape === "square") return <rect x="10" y="12" width="44" height="42" rx="12" className={className} />;
  if (shape === "tall") return <rect x="14" y="8" width="36" height="48" rx="18" className={className} />;
  return <circle cx="32" cy="34" r="22" className={className} />;
}

function Eyes({ kind }: { kind: number }) {
  if (kind === 1) {
    return (
      <g className="fill-surface-raised">
        <ellipse cx="24" cy="32" rx="4" ry="5" />
        <ellipse cx="40" cy="32" rx="4" ry="5" />
        <circle cx="25" cy="33" r="2" className="fill-ink-primary" />
        <circle cx="41" cy="33" r="2" className="fill-ink-primary" />
      </g>
    );
  }
  if (kind === 2) {
    return (
      <g className="stroke-ink-primary" strokeWidth="2.5" strokeLinecap="round" fill="none">
        <path d="M20 32 q4 -4 8 0" />
        <path d="M36 32 q4 -4 8 0" />
      </g>
    );
  }
  return (
    <g className="fill-ink-primary">
      <circle cx="24" cy="32" r="3" />
      <circle cx="40" cy="32" r="3" />
    </g>
  );
}

function Mouth({ kind }: { kind: number }) {
  if (kind === 1) return <ellipse cx="32" cy="43" rx="4" ry="3" className="fill-ink-primary" />;
  if (kind === 2) return <path d="M27 43 h10" className="stroke-ink-primary" strokeWidth="2.5" strokeLinecap="round" />;
  return <path d="M25 41 q7 6 14 0" className="stroke-ink-primary" strokeWidth="2.5" strokeLinecap="round" fill="none" />;
}

function Topper({ kind, className }: { kind: number; className: string }) {
  if (kind === 1) {
    return (
      <g>
        <path d="M32 12 v-6" className="stroke-ink-primary" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="32" cy="5" r="3" className={className} />
      </g>
    );
  }
  if (kind === 2) return <path d="M20 14 q12 -10 24 0 z" className={className} />;
  return null;
}

export function Mascot({ seed, shape, name, size = "md" }: { seed: string; shape: string; name: string; size?: keyof typeof SIZE }) {
  const value = hash(seed);
  const body = BODY[pick(value, 0, BODY.length)] as string;
  const topper = BODY[pick(value, 11, BODY.length)] as string;
  return (
    <svg role="img" aria-label={name} viewBox="0 0 64 64" className={`${SIZE[size]} shrink-0`}>
      <Body shape={shape} className={body} />
      <Topper kind={pick(value, 8, 3)} className={topper} />
      <Eyes kind={pick(value, 3, 3)} />
      <Mouth kind={pick(value, 5, 3)} />
      <g className="fill-surface-raised opacity-40">
        <circle cx="18" cy="40" r="3" />
        <circle cx="46" cy="40" r="3" />
      </g>
    </svg>
  );
}
