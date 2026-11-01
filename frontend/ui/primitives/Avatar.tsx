export function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return (
    <span role="img" aria-label={name} className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-xs font-medium text-ink-secondary">
      {initials}
    </span>
  );
}
