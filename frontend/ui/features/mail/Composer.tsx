"use client";

import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import type { Draft, Recipient } from "@/ui/client/contracts.generated";
import { useRemoveDraft, useSaveDraft, useSendMail } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

const ADDRESS = /^[^@\s<>]+@[^@\s<>]+$/;

const format = (people: readonly Recipient[] | undefined) => (people ?? []).map((person) => person.address).join(", ");

function parse(text: string): { people: Recipient[]; bad: string[] } {
  const parts = text.split(/[,;\s]+/).filter(Boolean);
  return { people: parts.filter((part) => ADDRESS.test(part)).map((address) => ({ address })), bad: parts.filter((part) => !ADDRESS.test(part)) };
}

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

export function Composer({ initial, dropped = [], onDone }: { initial: Draft; dropped?: readonly string[]; onDone: () => void }) {
  const toast = useToast();
  const [to, setTo] = useState(format(initial.to));
  const [cc, setCc] = useState(format(initial.cc));
  const [bcc, setBcc] = useState(format(initial.bcc));
  const [subject, setSubject] = useState(initial.subject ?? "");
  const [body, setBody] = useState(initial.body ?? "");
  const save = useSaveDraft();
  const send = useSendMail();
  const remove = useRemoveDraft();
  const [id, setId] = useState(initial.id ?? null);

  const parsed = { to: parse(to), cc: parse(cc), bcc: parse(bcc) };
  const bad = [...parsed.to.bad, ...parsed.cc.bad, ...parsed.bcc.bad];
  const noRecipients = parsed.to.people.length + parsed.cc.people.length + parsed.bcc.people.length === 0;
  const draft = (): Draft => ({ ...initial, id, to: parsed.to.people, cc: parsed.cc.people, bcc: parsed.bcc.people, subject, body });

  return (
    <form
      aria-label={t("mail.compose")}
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        send.mutate(draft(), {
          onSuccess: () => {
            toast({ title: t("mail.sent") });
            onDone();
          },
        });
      }}
    >
      {dropped.length > 0 ? <p className="text-md text-status-warning">{t("mail.dropped", { people: dropped.join(", ") })}</p> : null}
      <Field label={t("mail.to")} {...(bad.length ? { error: t("mail.badAddress", { address: bad[0] ?? "" }) } : {})}>
        {({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={to} onChange={(event) => setTo(event.target.value)} {...control} />}
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("mail.cc")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={cc} onChange={(event) => setCc(event.target.value)} {...control} />}</Field>
        <Field label={t("mail.bcc")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={bcc} onChange={(event) => setBcc(event.target.value)} {...control} />}</Field>
      </div>
      <Field label={t("mail.subject")}>{({ invalid, ...control }) => <Input invalid={invalid} value={subject} onChange={(event) => setSubject(event.target.value)} {...control} />}</Field>
      <Field label={t("mail.body")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={8} value={body} onChange={(event) => setBody(event.target.value)} {...control} />}</Field>
      {send.isError ? <ErrorState title={t("mail.sendFailed")} description={messageOf(send.error)} /> : null}
      {save.isError ? <ErrorState title={t("mail.saveFailed")} description={messageOf(save.error)} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" loading={send.isPending} disabled={noRecipients || bad.length > 0}>
          {t("mail.send")}
        </Button>
        <Button
          loading={save.isPending}
          onClick={() =>
            save.mutate(draft(), {
              onSuccess: (saved) => {
                setId(saved.id ?? null);
                toast({ title: t("mail.draftSaved") });
              },
            })
          }
        >
          {t("mail.saveDraft")}
        </Button>
        <Button
          variant="quiet"
          onClick={() => {
            if (id) remove.mutate(id);
            onDone();
          }}
        >
          {t("mail.discard")}
        </Button>
      </div>
    </form>
  );
}
