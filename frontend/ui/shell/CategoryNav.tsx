"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { Icon } from "@/ui/icons";
import { useCategories, useSaveCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { ActiveMark } from "@/ui/primitives/Motion";
import { t } from "@/ui/strings";
import { categoryHref, customCategories } from "./customMail";
import { MailNavMenu } from "./MailNavMenu";


function NewCategory() {
  const router = useRouter();
  const save = useSaveCategory();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<"smart" | "exact">("smart");
  const [priority, setPriority] = useState(true);
  const failed = save.error instanceof ApiRequestError ? save.error.detail.message : null;
  return (
    <Dialog title={t("categories.new")} description={t("categories.new.description")} open={open} onOpenChange={setOpen} trigger={<IconButton icon="add" label={t("categories.new")} />}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(
            { name: name.trim(), in_priority: priority, mode, description: description.trim(), ...(mode === "exact" && sender.trim() ? { sender: sender.trim() } : {}), ...(mode === "exact" && subject.trim() ? { subject: subject.trim() } : {}) },
            {
              onSuccess: () => {
                router.push(`/mail/category/${encodeURIComponent(name.trim())}`);
                setOpen(false);
                setName("");
                setSender("");
                setSubject("");
                setDescription("");
                setMode("smart");
                setPriority(true);
              },
            },
          );
        }}
      >
        <Field label={t("categories.name")} {...(failed ? { error: failed } : {})}>{({ invalid, ...control }) => <Input invalid={invalid} value={name} onChange={(event) => setName(event.target.value)} {...control} />}</Field>
        <Select label={t("categories.mode")} value={mode} options={[{ value: "smart", label: t("categories.mode.smart") }, { value: "exact", label: t("categories.mode.exact") }]} onChange={(value) => setMode(value as "smart" | "exact")} />
        {mode === "smart" ? <Field label={t("categories.smartDescription")}>{({ invalid, ...control }) => <Input invalid={invalid} value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} {...control} />}</Field> : <>
          <Field label={t("categories.sender")} hint={t("categories.sender.hint")}>{({ invalid, ...control }) => <Input invalid={invalid} spellCheck={false} value={sender} onChange={(event) => setSender(event.target.value)} {...control} />}</Field>
          <Field label={t("categories.subject")}>{({ invalid, ...control }) => <Input invalid={invalid} value={subject} onChange={(event) => setSubject(event.target.value)} {...control} />}</Field>
        </>}
        <Checkbox label={t("categories.priority")} checked={priority} onChange={setPriority} />
        <div className="flex justify-end">
          <Button type="submit" variant="primary" loading={save.isPending} disabled={!name.trim() || (mode === "exact" && !sender.trim() && !subject.trim())}>
            {t("categories.create")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function CategoryNavActions({ collapsed }: { collapsed: boolean }) {
  if (collapsed) return null;
  return <div className="flex shrink-0 items-center justify-between px-2 text-sm text-ink-muted"><span>{t("nav.categories")}</span><NewCategory /></div>;
}

/** Folders the person or an agent made. They live in the sidebar beside the fixed ones. */
export function CategoryNav({ collapsed, visibleHrefs }: { collapsed: boolean; visibleHrefs?: ReadonlySet<string> }) {
  const categories = useCategories();
  const pathname = usePathname();
  if (collapsed) return null;
  const hrefOf = categoryHref;
  // A created folder must remain reachable even before any mail is assigned to it.
  const rows = customCategories(categories.data?.categories ?? []).filter((item) => !visibleHrefs || visibleHrefs.has(hrefOf(item.name)));
  return (
    <section aria-label={t("nav.categories")}>
      <ul className="flex flex-col gap-px">
        {rows.map((item) => {
          const href = hrefOf(item.name);
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={item.name} data-testid="nav-category">
              <MailNavMenu href={href} scope={{ folder: "all", category: item.name }} category={item}>
              <Link href={href} aria-current={active ? "page" : undefined} className={`focus-ring press relative flex items-center gap-2 rounded-md px-2 py-1 text-md transition-colors duration-fast ${active ? "text-ink-primary" : "text-ink-secondary hover:bg-surface-raised hover:text-ink-primary"}`}>
                {active ? <ActiveMark group="nav-active" /> : null}
                <span aria-hidden className={`relative flex shrink-0 ${item.in_priority ? "text-accent-default" : ""}`}>
                  <Icon name="folder" />
                </span>
                <span className="relative min-w-0 flex-1 truncate">{item.name}</span>
                {item.unread ? <span className="relative text-sm tabular-nums text-ink-muted">{item.unread}</span> : null}
              </Link>
              </MailNavMenu>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
