"use client";

import { copyText } from "@/ui/client/browser";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { useAvailableModels, useCancelLogin, useDisconnect, useModelStatus, useSelectModel, useStartLogin, useTestModel } from "@/ui/client/models";
import { useListProviderModels, useModelProvider, useSaveModelProvider } from "@/ui/client/work";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Segmented } from "@/ui/primitives/Segmented";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Switch } from "@/ui/primitives/Switch";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { t } from "@/ui/strings";

const messageOf = (error: unknown) => (error instanceof ApiRequestError ? error.detail.message : t("settings.models.error"));

function SignIn({ code, url }: { code: string; url: string }) {
  const toast = useToast();
  const cancel = useCancelLogin();
  const copy = () => void copyText(code).then(() => toast({ title: t("settings.models.copied") }));
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-md text-ink-secondary">{t("settings.models.signIn.steps")}</p>
      <p data-testid="user-code" className="rounded-md bg-surface-sunken px-4 py-2 font-mono text-xl tabular-nums text-ink-primary">
        {code}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <TextLink href={url} target="_blank" rel="noreferrer">
          {t("settings.models.signIn.open")}
        </TextLink>
        <Button onClick={copy}>{t("settings.models.signIn.copy")}</Button>
        <Button variant="quiet" loading={cancel.isPending} onClick={() => cancel.mutate(undefined)}>
          {t("settings.models.signIn.cancel")}
        </Button>
      </div>
      <p role="status" className="flex items-center gap-2 text-md text-ink-muted">
        <StatusDot tone="waiting" />
        {t("settings.models.signIn.waiting")}
      </p>
    </div>
  );
}

function Connected({ email, plan, selected, managed = false }: { email: string | null | undefined; plan: string | null | undefined; selected: string | null | undefined; managed?: boolean }) {
  const models = useAvailableModels(true);
  const select = useSelectModel();
  const disconnect = useDisconnect();
  const test = useTestModel();
  const [prompt, setPrompt] = useState(t("settings.models.test.default"));
  const options = (models.data?.models ?? []).map((model) => ({ value: model.id, label: model.name }));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex min-w-0 items-center gap-2 text-md text-ink-secondary">
          <StatusDot tone="done" />
          <span className="truncate">{email ?? t("settings.models.connected")}</span>
          {plan ? <span className="text-sm text-ink-muted">{plan}</span> : null}
        </p>
        {managed ? null : (
          <Button variant="quiet" loading={disconnect.isPending} onClick={() => disconnect.mutate(undefined)}>
            {t("settings.models.disconnect")}
          </Button>
        )}
      </div>
      {models.isPending ? <Skeleton className="h-6 w-full" /> : null}
      {models.isError ? <ErrorState title={t("settings.models.list.error")} description={messageOf(models.error)} onRetry={() => void models.refetch()} /> : null}
      {models.isSuccess && options.length === 0 ? <p className="text-md text-ink-muted">{t("settings.models.list.empty")}</p> : null}
      {options.length > 0 ? (
        <Field label={t("settings.models.choose")} {...(select.isError ? { error: messageOf(select.error) } : {})}>
          {({ id, invalid, "aria-describedby": describedBy }) => <Select id={id} invalid={invalid} {...(describedBy ? { describedBy } : {})} {...(selected ? { value: selected } : {})} placeholder={t("settings.models.choose.placeholder")} options={options} onChange={(model) => select.mutate(model)} />}
        </Field>
      ) : null}
      {selected ? (
        <form
          className="flex flex-col items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            test.mutate(prompt);
          }}
        >
          <div className="w-full">
            <Field label={t("settings.models.test.label")} hint={t("settings.models.test.hint")}>
              {({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} maxLength={4000} value={prompt} onChange={(event) => setPrompt(event.target.value)} {...control} />}
            </Field>
          </div>
          <Button type="submit" loading={test.isPending} disabled={!prompt.trim()}>
            {t("settings.models.test.send")}
          </Button>
          {test.isError ? <ErrorState title={t("settings.models.test.error")} description={messageOf(test.error)} /> : null}
          {test.isSuccess ? (
            <div data-testid="model-reply" className="w-full whitespace-pre-wrap rounded-md bg-surface-sunken p-3 text-md text-ink-primary">
              {test.data.text}
            </div>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}

function InternalServer() {
  const provider = useModelProvider();
  const save = useSaveModelProvider();
  const list = useListProviderModels();
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [tools, setTools] = useState<boolean | null>(null);
  const data = provider.data;
  if (!data) return <Skeleton className="h-6 w-full" />;
  const url = baseUrl ?? data.base_url ?? "";
  const supports = tools ?? data.supports_tools ?? false;
  const options = (list.data?.models ?? []).map((model) => ({ value: model.id, label: model.name }));
  const store = (model: string | null) => save.mutate({ provider: "litellm", base_url: url, model, supports_tools: supports, ...(apiKey ? { api_key: apiKey } : {}) });
  return (
    <div className="flex flex-col gap-3">
      <Field label={t("settings.models.internal.url")} hint={t("settings.models.internal.urlHint")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={url} onChange={(event) => setBaseUrl(event.target.value)} {...control} />}</Field>
      <Field label={t("settings.models.internal.key")} {...(data.has_key ? { hint: t("settings.models.internal.keySaved") } : {})}>{({ invalid, ...control }) => <Input type="password" autoComplete="off" invalid={invalid} value={apiKey} onChange={(event) => setApiKey(event.target.value)} {...control} />}</Field>
      <Switch label={t("settings.models.internal.tools")} checked={supports} onChange={setTools} />
      {list.isError ? <ErrorState title={t("settings.models.list.error")} description={messageOf(list.error)} /> : null}
      {save.isError ? <ErrorState title={t("settings.models.error")} description={messageOf(save.error)} /> : null}
      <div><Button loading={list.isPending} disabled={!url} onClick={() => list.mutate({ base_url: url, ...(apiKey ? { api_key: apiKey } : {}) }, { onSuccess: result => { const first = result.models[0]; if (first && !result.models.some(item => item.id === data.model)) store(first.id); } })}>{t("settings.models.internal.load")}</Button></div>
      {options.length ? <Field label={t("settings.models.choose")}>{({ invalid, id }) => <Select id={id} invalid={invalid} {...(data.model ? { value: data.model } : {})} placeholder={t("settings.models.choose.placeholder")} options={options} onChange={(model) => store(model)} />}</Field> : null}
      {data.provider === "litellm" && data.model ? <p className="text-md text-ink-secondary">{t("settings.models.internal.using", { model: data.model })}</p> : null}
    </div>
  );
}

export function ModelSettings() {
  const status = useModelStatus();
  const start = useStartLogin();
  const login = status.data?.login;
  const provider = useModelProvider();
  const saveProvider = useSaveModelProvider();
  const active = provider.data?.provider ?? "chatgpt";
  if (status.data?.managed) {
    return (
      <Card title={t("settings.models.title")} description={t("settings.models.description.system")}>
        <Connected email={null} plan={null} selected={status.data.selected_model} managed />
      </Card>
    );
  }
  return (
    <Card title={t("settings.models.title")} description={t("settings.models.description")}>
      <div className="mb-4">
        <Segmented
          label={t("settings.models.provider")}
          value={active}
          options={[{ value: "chatgpt", label: t("settings.models.provider.chatgpt") }, { value: "litellm", label: t("settings.models.provider.internal") }]}
          onChange={(next) => saveProvider.mutate({ provider: next as "chatgpt" | "litellm", base_url: provider.data?.base_url ?? null, model: provider.data?.model ?? null, supports_tools: provider.data?.supports_tools ?? false })}
        />
      </div>
      {active === "litellm" ? <InternalServer /> : null}
      <div aria-busy={status.isPending} className={active === "litellm" ? "hidden" : ""}>
        {status.isPending ? <Skeleton className="h-6 w-full" /> : null}
        {status.isError ? <ErrorState title={t("settings.models.status.error")} description={messageOf(status.error)} onRetry={() => void status.refetch()} /> : null}
        {status.data?.connected ? <Connected email={status.data.account_email} plan={status.data.plan} selected={status.data.selected_model} /> : null}
        {status.data && !status.data.connected && login?.state === "waiting" && login.user_code && login.verification_url ? <SignIn code={login.user_code} url={login.verification_url} /> : null}
        {status.data && !status.data.connected && login?.state !== "waiting" ? (
          <div className="flex flex-col items-start gap-3">
            {login?.state === "failed" ? <ErrorState title={t("settings.models.signIn.failed")} {...(login.error ? { description: login.error } : {})} /> : null}
            {start.isError ? <ErrorState title={t("settings.models.signIn.failed")} description={messageOf(start.error)} /> : null}
            <Button variant="primary" loading={start.isPending} onClick={() => start.mutate(undefined)}>
              {t("settings.models.connect")}
            </Button>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
