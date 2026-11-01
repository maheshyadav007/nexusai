const TONES = { done: "bg-agent-done", failed: "bg-agent-failed", waiting: "bg-agent-waiting", running: "bg-agent-running", idle: "bg-line-strong" } as const;

export function StatusDot({ tone }: { tone: keyof typeof TONES }) {
  return <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${TONES[tone]}`} />;
}
