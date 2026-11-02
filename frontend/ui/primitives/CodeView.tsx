/** Code and logs with line numbers, so a line can be found and talked about. */
export function CodeView({ text, label }: { text: string; label: string }) {
  const lines = text.split("\n");
  return (
    <div role="region" aria-label={label} tabIndex={0} className="focus-ring overflow-x-auto rounded-md border border-line-subtle bg-surface-raised">
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
    </div>
  );
}
