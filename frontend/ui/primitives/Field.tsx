import { useId, type ReactNode } from "react";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  invalid: boolean;
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: (control: FieldControlProps) => ReactNode }) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-md font-medium text-ink-primary">
        {label}
      </label>
      {children({ id, invalid: Boolean(error), ...(note ? { "aria-describedby": noteId } : {}) })}
      {note ? (
        <p id={noteId} role={error ? "alert" : undefined} className={`text-sm ${error ? "text-status-danger" : "text-ink-muted"}`}>
          {note}
        </p>
      ) : null}
    </div>
  );
}
