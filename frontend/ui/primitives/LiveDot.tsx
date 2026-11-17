/** One signal for "alive right now", the same in the chat, the team and the session list: a dot
 * with a soft ring. Running is the accent; waiting on someone is amber. Reduced motion keeps the dot. */
export function LiveDot({ tone = "running", label }: { tone?: "running" | "waiting"; label?: string }) {
  const color = tone === "waiting" ? "bg-agent-waiting" : "bg-agent-running";
  return (
    <span {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })} className="relative inline-flex h-2 w-2 shrink-0">
      <span className={`absolute inset-0 animate-live-ring rounded-full motion-reduce:hidden ${color}`} />
      <span className={`relative inline-flex h-2 w-2 rounded-full ${color}`} />
    </span>
  );
}
