export function Avatar({ name, size = "sm" }: { name: string; size?: "sm" | "md" }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  return (
    <span role="img" aria-label={name} className={`inline-flex shrink-0 items-center justify-center rounded-full font-medium ${size === "md" ? "h-6 w-6 bg-accent-default/10 text-sm text-accent-default ring-1 ring-inset ring-accent-default/20" : "h-5 w-5 bg-surface-sunken text-xs text-ink-secondary"}`}>
      {initials}
    </span>
  );
}
