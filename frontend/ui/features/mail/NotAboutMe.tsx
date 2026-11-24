"use client";

import { useState } from "react";
import { useMe, useNotAboutMe } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Input } from "@/ui/primitives/Input";
import { Popover } from "@/ui/primitives/Popover";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

/** A reply let through because it named the person, when it wasn't about them: back behind its
 * folder, and the name that misled fixed so it holds from now on. */
export function NotAboutMe({ thread, quote }: { thread: number; quote: string }) {
  const me = useMe().data;
  const undo = useNotAboutMe();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [other, setOther] = useState("");
  const said = quote.toLocaleLowerCase();
  // Which of the person's names the reply used, so the one that misled can be dropped.
  const used = [...(me?.names ?? []), ...(me?.ids ?? [])].filter((name) => said.includes(name.toLocaleLowerCase()));
  const send = (input: { not_you?: string; stop?: string }) =>
    undo.mutate({ thread, ...input }, { onSuccess: () => { setOpen(false); toast({ title: t("me.notAboutMe.done") }); } });
  return (
    <Popover
      label={t("me.notAboutMe")}
      open={open}
      onOpenChange={setOpen}
      trigger={<Button variant="quiet" data-testid="not-about-me">{t("me.notAboutMe")}</Button>}
    >
      <div className="flex w-72 flex-col gap-3 p-3">
        <p className="text-md font-medium text-ink-primary">{t("me.notAboutMe.title", { quote })}</p>
        <form className="flex flex-col gap-2" onSubmit={(event) => { event.preventDefault(); if (other.trim()) send({ not_you: other.trim() }); }}>
          <label className="text-sm text-ink-secondary" htmlFor={`not-you-${thread}`}>{t("me.notAboutMe.someoneElse")}</label>
          <div className="flex gap-2">
            <Input id={`not-you-${thread}`} value={other} onChange={(event) => setOther(event.target.value)} />
            <Button type="submit" disabled={!other.trim()} loading={undo.isPending}>{t("me.add")}</Button>
          </div>
        </form>
        {used.map((name) => <Button key={name} variant="quiet" onClick={() => send({ stop: name })}>{t("me.notAboutMe.stop", { name })}</Button>)}
        <Button variant="quiet" onClick={() => send({})}>{t("me.notAboutMe.just")}</Button>
      </div>
    </Popover>
  );
}
