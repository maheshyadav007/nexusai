/** Rows from a spreadsheet, with the first as the heading. Long ones scroll inside themselves. */
export function TableView({ rows, label }: { rows: readonly (readonly string[])[]; label: string }) {
  const [head, ...body] = rows;
  if (!head) return null;
  return (
    <div role="region" aria-label={label} tabIndex={0} className="focus-ring overflow-auto rounded-md border border-line-subtle bg-surface-raised">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th key={index} scope="col" className="whitespace-nowrap border-b border-line-strong px-3 py-2 text-left font-medium text-ink-primary">{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, index) => (
            <tr key={index} className="border-b border-line-subtle last:border-b-0">
              {row.map((cell, column) => (
                <td key={column} className="whitespace-nowrap px-3 py-1 tabular-nums text-ink-secondary">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
