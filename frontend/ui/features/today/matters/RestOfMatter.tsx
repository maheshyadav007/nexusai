"use client";

import { useEffect, useState } from "react";
import { useRestQuestion } from "@/ui/client/rest";
import { useCloseMatterItems, useMatterRelated, useReopenMatterItems } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { useToast } from "@/ui/primitives/Toast";
import { t, tn, type StringKey } from "@/ui/strings";
import { useDue } from "./parts";

/** When something in a matter is finished, one question about the rest of it. Children went
 *  with their parent already; these are siblings, so nothing closes without a yes. Ticked to
 *  start with only what the same email asked for. Mounted once, for every screen. */
export function RestOfMatter() {
  const [trigger, clear] = useRestQuestion();
  const related = useMatterRelated(trigger || null);
  const close = useCloseMatterItems();
  const reopen = useReopenMatterItems();
  const toast = useToast();
  const due = useDue();
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const items = related.data?.items ?? [];
  useEffect(() => setTicked(new Set(items.filter((item) => item.suggested).map((item) => item.ref))), [related.data]);
  // Nothing else open: nothing to ask.
  useEffect(() => {
    if (trigger && related.isSuccess && !items.length) clear();
  }, [trigger, related.isSuccess, items.length]);
  if (!trigger || !items.length) return null;
  const answer = (closing: string[]) => {
    const keep = items.map((item) => item.ref).filter((ref) => !closing.includes(ref));
    close.mutate(
      { trigger, close: closing, keep },
      {
        onSuccess: ({ closed }) =>
          toast(
            closed
              ? { title: tn("rest.closed", closed), action: { label: t("matters.undo"), run: () => reopen.mutate(closing) } }
              : { title: t("rest.kept") },
          ),
        onError: (error) => toast({ title: error.message, tone: "danger" }),
      },
    );
    clear();
  };
  return (
    <Dialog title={t("rest.title", { title: related.data?.title ?? "" })} description={t("rest.description")} open onOpenChange={(open) => (open ? null : clear())}>
      <ul data-testid="rest-of-matter" className="flex flex-col gap-3">
        {items.map((item) => (
          <li key={item.ref} className="flex flex-col gap-1">
            <Checkbox
              label={item.title}
              checked={ticked.has(item.ref)}
              onChange={(on) => {
                const next = new Set(ticked);
                if (on) next.add(item.ref);
                else next.delete(item.ref);
                setTicked(next);
              }}
            />
            <span className="pl-5 text-sm text-ink-muted">
              {[t(`rest.kind.${item.kind}` as StringKey), item.when ? due(item.when).text : null, item.why].filter(Boolean).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button variant="quiet" onClick={() => answer([])}>{t("rest.keep")}</Button>
        <Button variant="primary" data-testid="rest-close" disabled={!ticked.size} loading={close.isPending} onClick={() => answer([...ticked])}>{t("rest.close")}</Button>
      </div>
    </Dialog>
  );
}
