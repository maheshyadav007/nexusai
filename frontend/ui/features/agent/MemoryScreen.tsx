"use client";

import { newId } from "@/ui/client/browser";
import { useEffect, useState } from "react";
import { AgentKnows, AgentSees } from "./AgentKnows";
import type { MemoryFile, PromptFile } from "@/ui/client/contracts.generated";
import { useDecideMemory, useMemory, usePrompts, useRemoveMemory, useSaveMemory, useSavePrompt } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input } from "@/ui/primitives/Input";
import { TextEditor, TextView } from "@/ui/primitives/TextView";
import { PageHeader } from "@/ui/primitives/PageHeader";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { Tabs } from "@/ui/primitives/Tabs";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

function PromptEditor({ prompt, startsOpen }: { prompt: PromptFile; startsOpen: boolean }) {
  const toast = useToast();
  const save = useSavePrompt();
  const [content, setContent] = useState(prompt.content);
  useEffect(() => setContent(prompt.content), [prompt.content]);
  const summary = prompt.content.trim().split("\n")[0];
  return (
    <ExpandRow label={t("prompts.open", { title: prompt.title })} defaultOpen={startsOpen} title={prompt.title} meta={summary || t(prompt.kind === "agent" ? "prompts.agent.description" : "prompts.empty")}>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ kind: prompt.kind, name: prompt.name, content }, { onSuccess: () => toast({ title: t("prompts.saved") }) });
        }}
      >
        {prompt.base ? (
          <details className="text-sm text-ink-secondary">
            <summary className="focus-ring cursor-pointer rounded-sm">{t("prompts.base")}</summary>
            <div className="mt-2"><TextView title={t("prompts.base")} text={prompt.base} /></div>
          </details>
        ) : null}
        <TextEditor label={prompt.title} rows={10} value={content} onChange={setContent} />
        <div><Button type="submit" loading={save.isPending} disabled={content === prompt.content}>{t("settings.save")}</Button></div>
      </form>
    </ExpandRow>
  );
}

export function PromptsEditor({ only }: { only?: readonly string[] }) {
  const prompts = usePrompts();
  if (prompts.isPending) return <Skeleton className="h-6 w-full" />;
  if (prompts.isError) return <ErrorState title={t("prompts.error")} onRetry={() => void prompts.refetch()} />;
  const shown = prompts.data.prompts.filter((prompt) => !only || only.includes(prompt.name));
  return (
    <div className="flex flex-col gap-2">
      {shown.map((prompt) => <PromptEditor key={`${prompt.kind}-${prompt.name}`} prompt={prompt} startsOpen={Boolean(only)} />)}
    </div>
  );
}

function MemoryRow({ file }: { file: MemoryFile }) {
  const save = useSaveMemory();
  const remove = useRemoveMemory();
  const [content, setContent] = useState(file.content);
  useEffect(() => setContent(file.content), [file.content]);
  return (
    <li data-testid="memory-file" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
      <p className="text-sm text-ink-muted">{file.agent ? t("memory.agentLevel", { agent: file.agent }) : t("memory.userLevel")} · {file.name}</p>
      <TextEditor label={file.name} value={content} onChange={setContent} />
      <div className="flex gap-2">
        <Button loading={save.isPending} disabled={content === file.content} onClick={() => save.mutate({ path: file.path, name: file.name, content })}>{t("settings.save")}</Button>
        <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(file.path)}>{t("memory.forget")}</Button>
      </div>
    </li>
  );
}

function MemoryBrowser() {
  const [search, setSearch] = useState("");
  const memory = useMemory(search);
  const save = useSaveMemory();
  const decide = useDecideMemory();
  const [note, setNote] = useState("");
  const files = memory.data?.files ?? [];
  const proposals = memory.data?.proposals ?? [];
  return (
    <div className="flex flex-col gap-4">
      {proposals.length ? (
        <Card title={t("memory.review")} description={t("memory.review.description")}>
          <ul className="flex flex-col gap-3">
            {proposals.map((proposal) => (
              <li key={proposal.id} data-testid="memory-proposal" className="flex flex-col gap-2 rounded-md border border-line-subtle p-3">
                <p className="break-words text-md text-ink-primary">{proposal.text}</p>
                <p className="text-sm text-ink-muted">{proposal.agent}</p>
                <div className="flex gap-2">
                  <Button variant="primary" onClick={() => decide.mutate({ id: proposal.id, accept: true })}>{t("memory.keep")}</Button>
                  <Button onClick={() => decide.mutate({ id: proposal.id, accept: false })}>{t("memory.decline")}</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      <form
        className="flex items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate({ name: `note-${newId().slice(0, 8)}`, content: note }, { onSuccess: () => setNote("") });
        }}
      >
        <div className="min-w-0 flex-1"><Field label={t("memory.add")}>{({ invalid, ...control }) => <Input invalid={invalid} value={note} onChange={(event) => setNote(event.target.value)} {...control} />}</Field></div>
        <Button type="submit" disabled={!note.trim()} loading={save.isPending}>{t("memory.addAction")}</Button>
      </form>
      <Field label={t("memory.search")}>{({ invalid, ...control }) => <Input invalid={invalid} value={search} onChange={(event) => setSearch(event.target.value)} {...control} />}</Field>
      {memory.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {memory.isError ? <ErrorState title={t("memory.error")} onRetry={() => void memory.refetch()} /> : null}
      {memory.isSuccess && files.length === 0 ? <EmptyState icon="memory" title={t("memory.empty")} /> : null}
      <ul aria-label={t("memory.title")} className="flex flex-col gap-2">
        {files.map((file) => <MemoryRow key={file.path} file={file} />)}
      </ul>
    </div>
  );
}

export function MemoryScreen() {
  return (
    <div className="mx-auto flex max-w-reading flex-col gap-5 p-6">
      <PageHeader title={t("nav.memory")} />
      <Tabs label={t("nav.memory")} tabs={[{ value: "knows", label: t("knows.title"), content: <AgentKnows /> }, { value: "prompts", label: t("prompts.title"), content: <PromptsEditor /> }, { value: "memory", label: t("memory.title"), content: <MemoryBrowser /> }, { value: "sees", label: t("knows.sees.title"), content: <AgentSees /> }]} />
    </div>
  );
}
