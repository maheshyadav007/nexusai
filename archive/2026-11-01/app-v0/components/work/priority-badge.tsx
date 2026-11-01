import { Badge } from "@/components/ui/badge";
import type { Priority } from "@/lib/types";

const label: Record<Priority, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low"
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  return <Badge variant={priority}>{label[priority]}</Badge>;
}
