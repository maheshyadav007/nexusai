"use client";

import { useState } from "react";
import type { Skill, SkillProposal } from "@/ui/client/contracts.generated";
import { useRelativeTime } from "@/ui/client/format";
import { useAddSkill, useAgentName, useDecideSkill, useReapproveSkill, useRemoveSkill, useSkills } from "@/ui/client/work";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { ExpandRow } from "@/ui/primitives/ExpandRow";
import { Field } from "@/ui/primitives/Field";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { TextView } from "@/ui/primitives/TextView";
import { t } from "@/ui/strings";

function AddSkill() {
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const add = useAddSkill();
  return (
    <form
      aria-label={t("skills.add")}
      className="flex flex-col gap-3 rounded-lg border border-line-subtle bg-surface-raised p-4"
      onSubmit={(event) => {
        event.preventDefault();
        add.mutate(url.trim() ? { url: url.trim() } : { text }, { onSuccess: () => { setUrl(""); setText(""); } });
      }}
    >
      <p className="text-md font-medium text-ink-primary">{t("skills.add")}</p>
      <p className="text-sm text-ink-secondary">{t("skills.add.hint")}</p>
      <Field label={t("skills.add.url")}>{(control) => <Input {...control} value={url} onChange={(event) => setUrl(event.target.value)} inputMode="url" />}</Field>
      <Field label={t("skills.add.text")} {...(add.error ? { error: add.error.message } : {})}>
        {(control) => <Textarea {...control} value={text} onChange={(event) => setText(event.target.value)} rows={4} disabled={Boolean(url.trim())} />}
      </Field>
      <div>
        <Button type="submit" loading={add.isPending} disabled={!url.trim() && !text.trim()}>{t("skills.add.submit")}</Button>
      </div>
    </form>
  );
}

function who(agents: readonly string[], name: (id: string) => string): string {
  if (agents.includes("all")) return t("skills.everyone");
  return agents.map((id) => name(id) || id).join(", ");
}

function Proposal({ proposal }: { proposal: SkillProposal }) {
  const decide = useDecideSkill();
  const name = useAgentName();
  const relative = useRelativeTime();
  const by = proposal.proposed_by === "person" ? t("team.person") : name(proposal.proposed_by);
  return (
    <li data-testid="skill-proposal" className="flex flex-col gap-3 rounded-lg border border-line-strong bg-surface-raised p-4">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-lg font-medium text-ink-primary">{proposal.name}</h3>
        <span className="text-sm text-ink-muted">{t("skills.proposed", { who: by, when: relative(proposal.created) })}</span>
      </div>
      <p className="text-md text-ink-secondary">{proposal.description}</p>
      <dl className="grid grid-cols-1 gap-1 text-sm md:grid-cols-4">
        <dt className="text-ink-muted">{t("skills.source")}</dt>
        <dd className="break-words text-ink-primary md:col-span-3">{proposal.source}</dd>
        <dt className="text-ink-muted">{t("skills.loadedBy")}</dt>
        <dd className="text-ink-primary md:col-span-3">{who(proposal.agents, name)}</dd>
        <dt className="text-ink-muted">{t("skills.needs")}</dt>
        <dd className="text-ink-primary md:col-span-3">{proposal.needs_tools.join(", ") || t("skills.needsNothing")}</dd>
      </dl>
      {proposal.flags.length ? (
        <div data-testid="skill-flags" className="flex flex-col gap-1 rounded-md bg-surface-sunken p-3 text-sm">
          <p className="font-medium text-status-warning">{t("skills.flags")}</p>
          <ul className="flex flex-col gap-px text-ink-primary">{proposal.flags.map((flag) => <li key={flag} className="break-words">{flag}</li>)}</ul>
        </div>
      ) : <p className="text-sm text-ink-muted">{t("skills.noFlags")}</p>}
      <div className="flex flex-col gap-2">
        <p className="text-sm text-ink-secondary">{t("skills.readAll")}</p>
        {proposal.files.map((file) => <TextView key={file.path} title={file.path} text={file.text} />)}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ id: proposal.id, approve: true })}>{t("skills.approve")}</Button>
        <Button variant="quiet" onClick={() => decide.mutate({ id: proposal.id, approve: false })}>{t("skills.reject")}</Button>
      </div>
    </li>
  );
}

function SkillRow({ skill }: { skill: Skill }) {
  const reapprove = useReapproveSkill();
  const remove = useRemoveSkill();
  const relative = useRelativeTime();
  return (
    <li data-testid="skill" data-active={skill.active}>
      <ExpandRow
        label={t("skills.open", { skill: skill.name })}
        title={skill.name}
        meta={skill.description}
        aside={
          <span className="flex items-center gap-1">
            <Badge tone={skill.origin === "yours" ? "accent" : "neutral"}>{t(skill.origin === "yours" ? "team.yours" : "skills.builtIn")}</Badge>
            {skill.active ? null : <Badge tone="warning">{t("skills.off")}</Badge>}
          </span>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          {skill.problem ? (
            <div className="flex flex-wrap items-center gap-2 text-status-warning">
              <span>{skill.problem}</span>
              {skill.origin === "yours" && skill.description ? <Button loading={reapprove.isPending} onClick={() => reapprove.mutate({ name: skill.name })}>{t("skills.reapprove")}</Button> : null}
            </div>
          ) : null}
          <dl className="grid grid-cols-1 gap-1 md:grid-cols-4">
            <dt className="text-ink-muted">{t("skills.loadedBy")}</dt>
            <dd className="text-ink-primary md:col-span-3">{skill.agents.join(", ") || t("skills.nobody")}</dd>
            <dt className="text-ink-muted">{t("skills.used")}</dt>
            <dd className="tabular-nums text-ink-primary md:col-span-3">{skill.last_loaded ? t("skills.usedValue", { count: skill.loads ?? 0, when: relative(skill.last_loaded) }) : t("skills.neverUsed")}</dd>
            {skill.files.length > 1 ? <><dt className="text-ink-muted">{t("skills.files")}</dt><dd className="text-ink-primary md:col-span-3">{skill.files.join(", ")}</dd></> : null}
          </dl>
          {skill.body ? <TextView title={t("skills.body", { skill: skill.name })} text={skill.body} /> : null}
          {skill.origin === "yours" ? <div><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate({ name: skill.name })}>{t("skills.remove")}</Button></div> : null}
        </div>
      </ExpandRow>
    </li>
  );
}

export function SkillsScreen() {
  const listed = useSkills();
  const skills = listed.data?.skills ?? [];
  const proposals = listed.data?.proposals ?? [];
  if (listed.isPending) return <Skeleton className="h-6 w-full" />;
  if (listed.isError) return <ErrorState title={t("skills.error")} onRetry={() => void listed.refetch()} />;
  return (
    <div className="flex flex-col gap-5">
      <p className="text-md text-ink-secondary">{t("skills.description")}</p>
      {proposals.length ? (
        <section aria-label={t("skills.waiting")} className="flex flex-col gap-3">
          <h2 className="text-lg font-medium text-ink-primary">{t("skills.waiting")}</h2>
          <ul className="flex flex-col gap-3">{proposals.map((item) => <Proposal key={item.id} proposal={item} />)}</ul>
        </section>
      ) : null}
      <section aria-label={t("skills.installed")} className="flex flex-col gap-2">
        <h2 className="text-lg font-medium text-ink-primary">{t("skills.installed")}</h2>
        {skills.length ? <ul className="flex flex-col gap-2">{skills.map((skill) => <SkillRow key={skill.name} skill={skill} />)}</ul> : <EmptyState icon="agent" title={t("skills.empty")} />}
      </section>
      <AddSkill />
    </div>
  );
}
