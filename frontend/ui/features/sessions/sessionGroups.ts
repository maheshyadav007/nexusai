import type { SessionRow } from "@/ui/client/contracts.generated";
import { isManagedSession } from "@/ui/client/sessions";

export interface SessionGroups {
  waiting: SessionRow[];
  agents: SessionRow[];
  today: SessionRow[];
  earlier: SessionRow[];
}

/** One way to sort conversations, for the switcher and the Sessions page alike: what waits on
 * the person first, then the agents' own chats, then the rest by day. Newest first within each. */
export function groupSessions(rows: readonly SessionRow[], now = new Date()): SessionGroups {
  const dayStart = new Date(now);
  dayStart.setHours(0, 0, 0, 0);
  const groups: SessionGroups = { waiting: [], agents: [], today: [], earlier: [] };
  for (const row of rows) {
    if (row.status === "waiting") groups.waiting.push(row);
    else if (isManagedSession(row)) groups.agents.push(row);
    else if (new Date(row.updated) >= dayStart) groups.today.push(row);
    else groups.earlier.push(row);
  }
  return groups;
}
