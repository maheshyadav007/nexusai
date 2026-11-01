import type { UIMessage } from "ai";

export interface ToolPart {
  type: string;
  toolCallId: string;
  state: string;
  input?: Record<string, unknown>;
  output?: unknown;
  errorText?: string;
}

/** A tool with its own card in the conversation. Everything else folds into the trace. */
export const CARD_TOOLS = new Set(["ask_user", "send_mail", "create_reminder", "create_task", "create_category", "create_agent", "propose_task", "propose_reminder", "draft_reply"]);

export const toolName = (part: ToolPart) => part.type.slice("tool-".length);
export const isFinished = (part: ToolPart) => part.state === "output-available" || part.state === "output-denied" || part.state === "output-error";

export type Block = { kind: "text"; text: string; key: string } | { kind: "trace"; steps: (ToolPart | { type: "reasoning"; text: string })[]; key: string } | { kind: "card"; part: ToolPart; key: string };

/** Puts the parts in reading order: work folded into traces, with cards and words between them. */
export function toBlocks(message: UIMessage, pending: ReadonlySet<string>): Block[] {
  const blocks: Block[] = [];
  message.parts.forEach((raw, index) => {
    const part = raw as unknown as { type: string; text?: string };
    if (part.type === "text" && part.text) {
      blocks.push({ kind: "text", text: part.text, key: `text-${index}` });
      return;
    }
    const isTool = part.type.startsWith("tool-");
    if (isTool) {
      const tool = raw as unknown as ToolPart;
      // A decision being waited on can't be folded away.
      if (CARD_TOOLS.has(toolName(tool)) || pending.has(tool.toolCallId)) {
        blocks.push({ kind: "card", part: tool, key: tool.toolCallId });
        return;
      }
    }
    if (!isTool && part.type !== "reasoning") return;
    const step = isTool ? (raw as unknown as ToolPart) : { type: "reasoning" as const, text: part.text ?? "" };
    const last = blocks[blocks.length - 1];
    if (last?.kind === "trace") last.steps.push(step);
    else blocks.push({ kind: "trace", steps: [step], key: `trace-${index}` });
  });
  return blocks;
}

export const followUpsOf = (message: UIMessage): string[] => {
  const part = message.parts.find((item) => item.type === "data-followups") as { data?: { questions?: string[] } } | undefined;
  return part?.data?.questions ?? [];
};

export const failureOf = (message: UIMessage): string | null => {
  const part = message.parts.find((item) => item.type === "data-error") as { data?: { text?: string } } | undefined;
  return part?.data?.text ?? null;
};

export const textOf = (message: UIMessage) =>
  message.parts
    .flatMap((part) => (part.type === "text" ? [part.text] : []))
    .join("\n\n")
    .trim();

export const timeOf = (message: UIMessage): string | null => {
  const metadata = message.metadata as { time?: string | null } | undefined;
  return metadata?.time ?? null;
};
