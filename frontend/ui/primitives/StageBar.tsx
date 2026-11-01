const STAGES = 4;

/** NexusAI's signature: four segments showing how far a piece of work has got. */
export function StageBar({ label, completed, failed = false }: { label: string; completed: number; failed?: boolean }) {
  return (
    <span role="img" aria-label={label} className="inline-flex shrink-0 gap-1">
      {Array.from({ length: STAGES }, (_, index) => {
        const tone = index < completed ? "bg-agent-done" : index === completed ? (failed ? "bg-agent-failed" : "bg-agent-running") : "bg-line-strong";
        return <span key={index} className={`h-1 w-4 rounded-full ${tone}`} />;
      })}
    </span>
  );
}
