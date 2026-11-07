"use client";

import type { AgentCard, MapEdge, RunSpan } from "@/ui/client/contracts.generated";
import { useRelativeTime } from "@/ui/client/format";
import { useAgentMap, useAgentName, useRunTree, useRuns, useSeeAlerts } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Mascot } from "@/ui/primitives/Mascot";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t, type StringKey } from "@/ui/strings";

// The drawing's own units. It scales to its box, so these never reach the page as sizes.
const WIDTH = 640;
const HEIGHT = 440;
const FACE = 56;
const STATE_STROKE: Readonly<Record<string, string>> = {
  queued: "stroke-line-strong",
  working: "stroke-agent-running",
  input_required: "stroke-agent-waiting",
  reported: "stroke-agent-waiting",
  blocked: "stroke-agent-failed",
};
const STATE_FILL: Readonly<Record<string, string>> = {
  queued: "fill-line-strong",
  working: "fill-agent-running",
  input_required: "fill-agent-waiting",
  reported: "fill-agent-waiting",
  blocked: "fill-agent-failed",
};

function positions(cards: readonly AgentCard[]): Map<string, { x: number; y: number }> {
  // The default agent at the top, the rest around it.
  const ordered = [...cards].sort((a, b) => Number(b.default) - Number(a.default));
  const placed = new Map<string, { x: number; y: number }>();
  ordered.forEach((card, index) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * index) / Math.max(ordered.length, 1);
    placed.set(card.id, { x: WIDTH / 2 + (WIDTH / 2 - 90) * Math.cos(angle), y: HEIGHT / 2 - 10 + (HEIGHT / 2 - 90) * Math.sin(angle) });
  });
  return placed;
}

function Arrow({ edge, from, to, offset }: { edge: MapEdge; from: { x: number; y: number }; to: { x: number; y: number }; offset: number }) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  // Two tasks between the same pair sit side by side instead of on top of each other.
  const nx = -uy * offset;
  const ny = ux * offset;
  const gap = FACE / 2 + 6;
  const start = { x: from.x + ux * gap + nx, y: from.y + uy * gap + ny };
  const end = { x: to.x - ux * gap + nx, y: to.y - uy * gap + ny };
  const head = `${end.x},${end.y} ${end.x - ux * 10 - uy * 5},${end.y - uy * 10 + ux * 5} ${end.x - ux * 10 + uy * 5},${end.y - uy * 10 - ux * 5}`;
  const trouble = Boolean(edge.trouble);
  return (
    <g>
      <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} strokeWidth={trouble ? 3 : 2} strokeDasharray={edge.state === "queued" ? "6 4" : undefined} className={trouble ? "stroke-agent-failed" : STATE_STROKE[edge.state] ?? "stroke-line-strong"} />
      <polygon points={head} className={trouble ? "fill-agent-failed" : STATE_FILL[edge.state] ?? "fill-line-strong"} />
      <text x={(start.x + end.x) / 2 + nx} y={(start.y + end.y) / 2 + ny - 6} textAnchor="middle" className="fill-ink-secondary text-lg">{t("map.edgeLabel", { task: edge.task_id, messages: edge.messages })}</text>
    </g>
  );
}

function Drawing({ cards, edges }: { cards: readonly AgentCard[]; edges: readonly MapEdge[] }) {
  const placed = positions(cards);
  const pairs = new Map<string, number>();
  return (
    <svg role="img" aria-label={t("map.drawing")} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full rounded-lg border border-line-subtle bg-surface-raised">
      {edges.map((edge) => {
        const from = placed.get(edge.source);
        const to = placed.get(edge.target);
        if (!from || !to) return null;
        const key = [edge.source, edge.target].sort().join(">");
        const index = pairs.get(key) ?? 0;
        pairs.set(key, index + 1);
        return <Arrow key={edge.task_id} edge={edge} from={from} to={to} offset={(index - 0.5) * 10 * Math.sign(edge.source.localeCompare(edge.target) || 1)} />;
      })}
      {cards.map((card) => {
        const spot = placed.get(card.id);
        if (!spot) return null;
        const state = card.now?.state ?? "idle";
        return (
          <g key={card.id}>
            <circle cx={spot.x} cy={spot.y} r={FACE / 2 + 4} strokeWidth={3} className={`fill-surface-page ${state === "working" ? "stroke-agent-running" : state === "waiting" ? "stroke-agent-waiting" : state === "blocked" ? "stroke-agent-failed" : "stroke-line-subtle"}`} />
            <Mascot seed={card.mascot.seed} shape={card.mascot.style} name={card.name} place={{ x: spot.x - FACE / 2, y: spot.y - FACE / 2, size: FACE }} />
            <text x={spot.x} y={spot.y + FACE / 2 + 24} textAnchor="middle" className="fill-ink-primary text-xl">{card.name}</text>
            <text x={spot.x} y={spot.y + FACE / 2 + 44} textAnchor="middle" className="fill-ink-muted text-lg">{t(`team.now.${state === "working" || state === "waiting" || state === "blocked" ? `${state}Short` : state}` as StringKey)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function TeamMap() {
  const map = useAgentMap();
  const name = useAgentName();
  const seen = useSeeAlerts();
  const relative = useRelativeTime();
  if (map.isPending) return <Skeleton className="h-6 w-full" />;
  if (map.isError || !map.data) return <ErrorState title={t("map.error")} onRetry={() => void map.refetch()} />;
  const { cards, edges, cycles, alerts } = map.data;
  const who = (id: string) => (id === "person" ? t("team.person") : name(id) || id);
  const unseen = alerts.filter((alert) => !alert.seen);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-md text-ink-secondary">{t("map.description")}</p>
      <Drawing cards={cards} edges={edges} />
      {cycles.length ? (
        <p role="alert" className="text-md text-status-danger">{t("map.cycle", { agents: cycles.map((loop) => loop.map(who).join(" → ")).join("; ") })}</p>
      ) : null}
      <section aria-label={t("map.tasks")} className="flex flex-col gap-2">
        <h2 className="text-lg font-medium text-ink-primary">{t("map.tasks")}</h2>
        {edges.length ? (
          <ul className="flex flex-col gap-1 text-md">
            {edges.map((edge) => (
              <li key={edge.task_id} data-testid="map-edge" data-trouble={Boolean(edge.trouble)} className="flex flex-wrap items-baseline gap-2 border-b border-line-subtle py-2">
                <span className="text-ink-primary">{t("map.edge", { from: who(edge.source), to: who(edge.target), task: edge.task_id })}</span>
                <Badge tone={edge.trouble ? "danger" : "neutral"}>{t(`team.state.${edge.state}` as StringKey)}</Badge>
                <span className="text-sm text-ink-secondary">{t("map.waiting", { agent: who(edge.waiting) })}</span>
                {edge.trouble ? <span className="text-sm text-status-danger">{edge.trouble}</span> : null}
                <span className="w-full text-sm text-ink-muted">{edge.objective}</span>
              </li>
            ))}
          </ul>
        ) : <EmptyState icon="channel" title={t("map.noTasks")} />}
      </section>
      <section aria-label={t("map.alerts")} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-medium text-ink-primary">{t("map.alerts")}</h2>
          {unseen.length ? <Button variant="quiet" loading={seen.isPending} onClick={() => seen.mutate(undefined)}>{t("map.markSeen")}</Button> : null}
        </div>
        {alerts.length ? (
          <ul className="flex flex-col gap-1 text-md">
            {alerts.map((alert) => (
              <li key={alert.id} data-testid="monitor-alert" className="flex flex-wrap items-baseline gap-2 border-b border-line-subtle py-2">
                {alert.seen ? null : <Badge tone="warning">{t("map.new")}</Badge>}
                <span className="text-ink-primary">{alert.detail}</span>
                <span className="text-sm tabular-nums text-ink-muted">{relative(alert.time)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-ink-muted">{t("map.noAlerts")}</p>}
      </section>
    </div>
  );
}

const KIND_LABEL: Readonly<Record<string, StringKey>> = { run: "trace.kind.run", model: "trace.kind.model", tool: "trace.kind.tool", skill: "trace.kind.skill", message: "trace.kind.message" };

function Span({ span }: { span: RunSpan }) {
  const relative = useRelativeTime();
  const children = span.children ?? [];
  return (
    <li className="flex flex-col gap-1">
      <span className="flex flex-wrap items-baseline gap-2 text-sm">
        <Badge tone={span.kind === "run" ? "accent" : "neutral"}>{t(KIND_LABEL[span.kind] ?? "trace.kind.tool")}</Badge>
        <span className="break-words text-ink-primary">{span.name}</span>
        {span.status ? <span className={span.status === "done" || span.status === "running" ? "text-ink-muted" : "text-status-warning"}>{span.status}</span> : null}
        {span.tokens ? <span className="tabular-nums text-ink-muted">{t("trace.tokens", { count: span.tokens.toLocaleString() })}</span> : null}
        <span className="tabular-nums text-ink-muted">{relative(span.time)}</span>
      </span>
      {span.detail && span.kind !== "run" ? <span className="break-words pl-2 text-sm text-ink-muted">{span.detail}</span> : null}
      {children.length ? <ol className="flex flex-col gap-2 border-l border-line-subtle pl-4">{children.map((child) => <Span key={child.id} span={child} />)}</ol> : null}
    </li>
  );
}

function Tree({ turn }: { turn: number }) {
  const tree = useRunTree(turn);
  if (tree.isPending) return <Skeleton className="h-6 w-full" />;
  if (tree.isError || !tree.data) return <ErrorState title={t("trace.error")} onRetry={() => void tree.refetch()} />;
  return <ol aria-label={t("trace.tree")} className="flex flex-col gap-2"><Span span={tree.data} /></ol>;
}

function RunRow({ run }: { run: RunSpan }) {
  const relative = useRelativeTime();
  return (
    <li data-testid="run">
      <ExpandRow
        label={t("trace.open")}
        title={run.name}
        meta={t("trace.meta", { cause: run.detail ?? "", when: relative(run.time) })}
        aside={<Badge tone={run.status === "done" || run.status === "running" ? "neutral" : "warning"}>{run.status}</Badge>}
      >
        {/* Mounted only when opened, so a tree is read only for the run someone looks at. */}
        <Tree turn={Number(run.id.replace("run-", ""))} />
      </ExpandRow>
    </li>
  );
}

export function RunsScreen() {
  const runs = useRuns();
  const rows = runs.data?.runs ?? [];
  if (runs.isPending) return <Skeleton className="h-6 w-full" />;
  if (runs.isError) return <ErrorState title={t("trace.error")} onRetry={() => void runs.refetch()} />;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-md text-ink-secondary">{t("trace.description")}</p>
      {rows.length ? <ul className="flex flex-col gap-2">{rows.map((run) => <RunRow key={run.id} run={run} />)}</ul> : <EmptyState icon="activity" title={t("trace.empty")} />}
    </div>
  );
}
