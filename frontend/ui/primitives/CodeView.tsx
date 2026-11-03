"use client";

import { t } from "@/ui/strings";
import { ExpandText } from "./TextView";

function Lines({ lines }: { lines: readonly string[] }) {
  return (
    <table className="w-full border-collapse font-mono text-sm">
      <tbody>
        {lines.map((line, index) => (
          <tr key={index}>
            <td className="select-none whitespace-nowrap border-r border-line-subtle px-3 py-px text-right tabular-nums text-ink-faint">{index + 1}</td>
            <td className="whitespace-pre px-3 py-px text-ink-primary">{line || " "}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Code and logs with line numbers, so a line can be found and talked about. */
export function CodeView({ text, label, expandable = true }: { text: string; label: string; expandable?: boolean }) {
  const lines = text.split("\n");
  return (
    <div className="relative">
      <div role="region" aria-label={label} tabIndex={0} className="focus-ring max-h-modal-height overflow-auto rounded-md border border-line-subtle bg-surface-raised">
        <Lines lines={lines} />
      </div>
      {expandable ? (
        <div className="absolute right-1 top-1">
          <ExpandText title={label}>
            <div role="region" aria-label={t("view.all", { title: label })} tabIndex={0} className="focus-ring min-h-0 flex-1 overflow-auto rounded-md border border-line-subtle bg-surface-raised">
              <Lines lines={lines} />
            </div>
          </ExpandText>
        </div>
      ) : null}
    </div>
  );
}
