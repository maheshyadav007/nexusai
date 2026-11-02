"use client";

import Link from "next/link";
import { useMailStatus } from "@/ui/client/mail";
import { useModelStatus } from "@/ui/client/models";
import { useDismissChecklist, useOnboarding } from "@/ui/client/onboarding";
import { usePstImports } from "@/ui/client/documents";
import { useSemantic } from "@/ui/client/semantic";
import { useCreateSession, useSessions } from "@/ui/client/sessions";
import { usePrompts } from "@/ui/client/work";
import { useAssistant } from "@/ui/features/assistant/AssistantProvider";
import { Icon } from "@/ui/icons";
import { Button } from "@/ui/primitives/Button";
import { Presence, Rise } from "@/ui/primitives/Motion";
import { Progress } from "@/ui/primitives/Progress";
import { Pressable } from "@/ui/primitives/Pressable";
import { t, type StringKey } from "@/ui/strings";

interface Item {
  id: string;
  title: StringKey;
  detail: StringKey;
  done: boolean;
  href?: string;
  run?: () => void;
}

const ROW = "flex items-center gap-3 rounded-md px-2 py-2 text-left transition-colors duration-fast hover:bg-surface-sunken";

function Row({ item }: { item: Item }) {
  const body = (
    <>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-md text-ink-primary">{t(item.title)}</span>
        <span className="truncate text-sm text-ink-muted">{t(item.detail)}</span>
      </span>
      <Icon name="chevronRight" className="h-3 w-3 shrink-0 text-ink-faint" />
    </>
  );
  if (item.href) {
    return (
      <Link href={item.href} data-testid="setup-item" className={`focus-ring press ${ROW}`}>
        {body}
      </Link>
    );
  }
  return (
    <Pressable data-testid="setup-item" onClick={item.run} className={`w-full ${ROW}`}>
      {body}
    </Pressable>
  );
}

/** What's left after the short setup. Each one is worth doing, and none of it stands in the way. */
export function FinishSetup() {
  const onboarding = useOnboarding();
  const dismiss = useDismissChecklist();
  const mail = useMailStatus();
  const model = useModelStatus();
  const semantic = useSemantic();
  const sessions = useSessions("");
  const prompts = usePrompts();
  const imports = usePstImports();
  const create = useCreateSession();
  const assistant = useAssistant();
  const items: readonly Item[] = [
    { id: "mail", title: "finish.mail.title", detail: "finish.mail.detail", done: Boolean(mail.data?.account), href: "/connectors" },
    { id: "model", title: "finish.model.title", detail: "finish.model.detail", done: Boolean(model.data?.connected), href: "/settings?section=models" },
    { id: "search", title: "finish.search.title", detail: "finish.search.detail", done: Boolean(semantic.data?.ready), href: "/settings?section=local-models" },
    {
      id: "interview",
      title: "finish.interview.title",
      detail: "finish.interview.detail",
      done: Boolean(sessions.data?.sessions.some((row) => row.agent === "interview")),
      run: () => create.mutate({ title: t("setup.interview.label"), agent: "interview" }, { onSuccess: (row) => assistant.openSession(row.id) }),
    },
    { id: "priorities", title: "finish.priorities.title", detail: "finish.priorities.detail", done: Boolean(prompts.data?.prompts.some((prompt) => prompt.kind === "personal" && prompt.content.trim() && prompt.content.trim() !== prompt.starter?.trim())), href: "/agent/memory" },
    { id: "archive", title: "finish.archive.title", detail: "finish.archive.detail", done: Boolean(imports.data?.imports.length), href: "/connectors" },
  ];
  const done = items.filter((item) => item.done).length;
  const showing = onboarding.data && !onboarding.data.checklist_dismissed && done < items.length;
  return (
    <Presence>
      {showing ? (
        <Rise as="section" key="finish-setup" aria-label={t("finish.title")} data-testid="finish-setup" className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4">
          <header className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-md font-medium text-ink-primary">{t("finish.title")}</h2>
              <p className="text-sm tabular-nums text-ink-muted">{t("finish.count", { done, total: items.length })}</p>
            </div>
            <Button variant="quiet" onClick={() => dismiss.mutate(undefined)}>{t("finish.dismiss")}</Button>
          </header>
          <Progress label={t("finish.title")} value={done} max={items.length} />
          <ul className="flex flex-col">
            <Presence>
              {items
                .filter((item) => !item.done)
                .map((item) => (
                  <Rise as="li" key={item.id} settle="position">
                    <Row item={item} />
                  </Rise>
                ))}
            </Presence>
          </ul>
        </Rise>
      ) : null}
    </Presence>
  );
}
