"use client";

import { useEffect, useRef, useState } from "react";
import type { GenerationPhase } from "@/ui/client/generation";
import { ApiRequestError } from "@/ui/client/api";
import type { Draft, DraftAttachment, Recipient } from "@/ui/client/contracts.generated";
import { query } from "@/ui/client/api";
import { useAttachFile, useRemoveDraft, useSaveDraft, useSendMail } from "@/ui/client/mail";
import { useProfile } from "@/ui/client/onboarding";
import type { SendProblem } from "@/ui/client/contracts.generated";
import { sizeOf } from "@/ui/features/documents/sizes";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { IconButton } from "@/ui/primitives/IconButton";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { GenerationSurface } from "@/ui/primitives/GenerationSurface";
import { Input, Textarea } from "@/ui/primitives/Input";
import { BareInput } from "@/ui/primitives/Pressable";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";
import { RecipientField } from "./RecipientField";

const ADDRESS = /^[^@\s<>]+@[^@\s<>]+$/;

const format = (people: readonly Recipient[] | undefined) => (people ?? []).map((person) => person.address).join(", ");

function parse(text: string): { people: Recipient[]; bad: string[] } {
  const parts = text.split(/[,;\s]+/).filter(Boolean);
  return { people: parts.filter((part) => ADDRESS.test(part)).map((address) => ({ address })), bad: parts.filter((part) => !ADDRESS.test(part)) };
}

// The usual line above a signature, so mail programs can tell it from the message.
const SIGNATURE_LINE = "-- ";
const FORWARDED = "\n\n---------- Forwarded message";

/** Their signature under what they write, once. In a forward it sits above the forwarded mail. */
export function signed(body: string, signature: string): string {
  if (!signature || body.includes(signature)) return body;
  const block = `${SIGNATURE_LINE}\n${signature}`;
  if (body.startsWith(FORWARDED)) return `\n\n${block}${body}`;
  return body.trim() ? `${body.trimEnd()}\n\n${block}` : `\n\n${block}`;
}

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

export function Composer({ initial, dropped = [], onDone, generation, generated, generationFailed = false }: { initial: Draft; dropped?: readonly string[]; onDone: () => void; generation?: GenerationPhase | undefined; generated?: { body: string; id: number | null } | null; generationFailed?: boolean }) {
  const toast = useToast();
  const [to, setTo] = useState(format(initial.to));
  const [cc, setCc] = useState(format(initial.cc));
  const [bcc, setBcc] = useState(format(initial.bcc));
  const [subject, setSubject] = useState(initial.subject ?? "");
  const [body, setBody] = useState(initial.body ?? "");
  const [files, setFiles] = useState<DraftAttachment[]>(initial.attachments ?? []);
  const attach = useAttachFile();
  const picker = useRef<HTMLInputElement>(null);
  const profile = useProfile();
  const signature = profile.data?.signature?.trim() ?? "";
  const signedOnce = useRef(false);
  // A new mail, reply or forward starts with the signature. A saved draft already has its own.
  useEffect(() => {
    if (signedOnce.current || initial.id || !profile.data) return;
    signedOnce.current = true;
    setBody((current) => signed(current, signature));
  }, [initial.id, profile.data, signature]);
  const save = useSaveDraft();
  const send = useSendMail();
  const remove = useRemoveDraft();
  const [id, setId] = useState(initial.id ?? null);
  useEffect(() => {
    if (!generated) return;
    setBody(signed(generated.body, signature));
    if (generated.id !== null) setId(generated.id);
    // The signature is read when the reply arrives, not again each time it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generated]);
  const generating = generation !== undefined;
  const [problems, setProblems] = useState<SendProblem[]>([]);
  const [countdown, setCountdown] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const opened = useRef(new Date().toISOString());

  const parsed = { to: parse(to), cc: parse(cc), bcc: parse(bcc) };
  const bad = [...parsed.to.bad, ...parsed.cc.bad, ...parsed.bcc.bad];
  const noRecipients = parsed.to.people.length + parsed.cc.people.length + parsed.bcc.people.length === 0;
  const draft = (): Draft => ({ ...initial, id, to: parsed.to.people, cc: parsed.cc.people, bcc: parsed.bcc.people, subject, body, attachments: files });
  const addFiles = async (picked: FileList | null) => {
    for (const file of Array.from(picked ?? [])) {
      try {
        const added = await attach.mutateAsync(file);
        setFiles((current) => [...current, added]);
      } catch (error) {
        toast({ title: t("mail.attachFailed", { name: file.name }), description: messageOf(error), tone: "danger" });
      }
    }
    if (picker.current) picker.current.value = "";
  };

  const deliver = () =>
    send.mutate(draft(), {
      onSuccess: () => {
        toast({ title: t("mail.sent") });
        onDone();
      },
    });

  /** A short window to change your mind, because a sent mail can't be recalled. */
  const startUndoWindow = (seconds: number) => {
    if (seconds <= 0) {
      deliver();
      return;
    }
    let left = seconds;
    setCountdown(left);
    timer.current = setInterval(() => {
      left -= 1;
      setCountdown(left);
      if (left <= 0) {
        if (timer.current) clearInterval(timer.current);
        setCountdown(null);
        deliver();
      }
    }, 1000);
  };
  const cancelSend = () => {
    if (timer.current) clearInterval(timer.current);
    setCountdown(null);
  };
  const checkThenSend = async (confirmed: boolean) => {
    const result = await query("mail.checkSend", { draft: draft(), written_after: opened.current });
    const found = result.problems ?? [];
    if (found.length && !confirmed) {
      setProblems(found);
      return;
    }
    setProblems([]);
    startUndoWindow(result.undo_seconds ?? 0);
  };
  const blocked = problems.some((problem) => problem.level === "block");

  return (
    <form
      aria-label={t("mail.compose")}
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        void checkThenSend(false);
      }}
    >
      {dropped.length > 0 ? <p className="text-md text-status-warning">{t("mail.dropped", { people: dropped.join(", ") })}</p> : null}
      <Field label={t("mail.to")} {...(bad.length ? { error: t("mail.badAddress", { address: bad[0] ?? "" }) } : {})}>
        {({ invalid, ...control }) => <RecipientField invalid={invalid} value={to} onChange={setTo} {...control} />}
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t("mail.cc")}>{({ invalid, ...control }) => <RecipientField invalid={invalid} value={cc} onChange={setCc} {...control} />}</Field>
        <Field label={t("mail.bcc")}>{({ invalid, ...control }) => <RecipientField invalid={invalid} value={bcc} onChange={setBcc} {...control} />}</Field>
      </div>
      <Field label={t("mail.subject")}>{({ invalid, ...control }) => <Input invalid={invalid} value={subject} onChange={(event) => setSubject(event.target.value)} {...control} />}</Field>
      {generating ? <div className="flex flex-col gap-2"><p className="text-md text-ink-primary">{t("mail.body")}</p><GenerationSurface phase={generation} label={t("generation.reply")} placeholder /></div> : <Field label={t("mail.body")}>{({ invalid, ...control }) => <Textarea invalid={invalid} rows={8} value={body} onChange={(event) => setBody(event.target.value)} {...control} />}</Field>}
      {files.length ? (
        <ul aria-label={t("mail.attachments")} className="flex flex-wrap gap-2">
          {files.map((file, index) => (
            <li key={`${file.upload ?? file.key ?? file.name}-${index}`} data-testid="draft-attachment" className="flex min-w-0 items-center gap-2 rounded-md border border-line-subtle py-px pl-3 pr-1 text-sm text-ink-secondary">
              <Icon name="attachment" className="h-3 w-3 shrink-0" />
              <span className="min-w-0 truncate text-ink-primary">{file.name}</span>
              {file.size ? <span className="shrink-0 tabular-nums text-ink-muted">{sizeOf(file.size)}</span> : null}
              <IconButton icon="close" label={t("mail.attachment.remove", { name: file.name })} className="p-1" onClick={() => setFiles((current) => current.filter((_, at) => at !== index))} />
            </li>
          ))}
        </ul>
      ) : null}
      {problems.length ? (
        <div role="alert" data-testid="send-checks" className="flex flex-col items-start gap-2 rounded-md border border-status-warning p-3">
          {problems.map((problem) => <p key={problem.check} className="text-md text-ink-primary">{problem.message}</p>)}
          {blocked ? null : <Button onClick={() => void checkThenSend(true)}>{t("mail.sendAnyway")}</Button>}
        </div>
      ) : null}
      {countdown !== null ? (
        <div role="status" className="flex items-center gap-3 rounded-md bg-surface-sunken p-3 text-md text-ink-primary">
          {t("mail.sending", { seconds: countdown })}
          <Button onClick={cancelSend}>{t("mail.undoSend")}</Button>
        </div>
      ) : null}
      {send.isError ? <ErrorState title={t("mail.sendFailed")} description={messageOf(send.error)} /> : null}
      {save.isError ? <ErrorState title={t("mail.saveFailed")} description={messageOf(save.error)} /> : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" loading={send.isPending} disabled={generating || generationFailed || noRecipients || bad.length > 0 || countdown !== null}>
          {t("mail.send")}
        </Button>
        <BareInput ref={picker} data-testid="mail-attach-input" type="file" multiple aria-label={t("mail.attach")} className="sr-only" onChange={(event) => void addFiles(event.target.files)} />
        <Button loading={attach.isPending} disabled={generating} onClick={() => picker.current?.click()}>
          <Icon name="attachment" className="h-4 w-4" />
          {t("mail.attach")}
        </Button>
        <Button
          loading={save.isPending}
          disabled={generating || generationFailed}
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
          disabled={generating}
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
