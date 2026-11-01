export function Progress({ label, value, max = 100 }: { label: string; value: number; max?: number }) {
  return <progress aria-label={label} value={value} max={max} className="nx-progress" />;
}
