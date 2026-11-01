import { PriorityBadge } from "@/components/work/priority-badge";
import type { ActionItem } from "@/lib/types";

export function ActionTable({ items }: { items: ActionItem[] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-hairline">
      <table className="w-full border-collapse text-left text-small">
        <thead className="bg-surface-2 text-caption text-ink-subtle">
          <tr>
            <th className="px-md py-sm font-medium">Action</th>
            <th className="px-md py-sm font-medium">Owner</th>
            <th className="px-md py-sm font-medium">Due</th>
            <th className="px-md py-sm font-medium">Source</th>
            <th className="px-md py-sm font-medium">Priority</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="border-t border-hairline bg-surface-1/78">
              <td className="px-md py-sm text-ink">{item.task}</td>
              <td className="px-md py-sm text-ink-muted">{item.owner}</td>
              <td className="px-md py-sm text-accent">{item.due}</td>
              <td className="px-md py-sm text-ink-subtle">{item.source}</td>
              <td className="px-md py-sm">
                <PriorityBadge priority={item.priority} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
