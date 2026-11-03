/** A count that means someone has to act, as opposed to a quiet tally like unread mail. */
export function AttentionCount({ value }: { value: number }) {
  return <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-accent-default px-1 text-sm font-medium tabular-nums text-accent-on">{value}</span>;
}
