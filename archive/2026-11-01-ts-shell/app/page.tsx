export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="text-4xl font-semibold tracking-tight">
        Nexus<span className="font-serif italic text-accent">AI</span>
      </h1>
      <p className="text-ink-muted">Fresh start. Building from the v9 design.</p>
      <a href="/designs/NexusAI%20v9.dc.html" className="font-mono text-sm text-accent hover:text-accent-deep">
        Open v9 design reference →
      </a>
    </main>
  );
}
