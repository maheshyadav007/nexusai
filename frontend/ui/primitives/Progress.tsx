/** A bar for how far along, or how big. Quiet draws it in the muted ink, for what the AI doesn't read. */
export function Progress({ label, value, max = 100, quiet = false }: { label: string; value: number; max?: number; quiet?: boolean }) {
  return <progress aria-label={label} value={value} max={max} className={`nx-progress ${quiet ? "nx-progress-quiet" : ""}`} />;
}
