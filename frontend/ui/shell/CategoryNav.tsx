"use client";

import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { ApiRequestError } from "@/ui/client/api";
import { Icon, type IconName } from "@/ui/icons";
import type { MailCategory } from "@/ui/client/contracts.generated";
import { useCategories, useSaveCategory } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input } from "@/ui/primitives/Input";
import { Select } from "@/ui/primitives/Select";
import { t } from "@/ui/strings";
import { AUTOMATED, CALENDAR, categoryHref, customCategories, isCurrentMail, keptFromAi, partlyKept } from "./customMail";
import { FolderLink } from "./FolderLink";
import { MailNavMenu } from "./MailNavMenu";


export function NewCategory() {
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
    <Dialog title={t("categories.new")} description={t("categories.new.description")} open={open} onOpenChange={setOpen} trigger={<IconButton icon="add" label={t("categories.new")} className="-my-1 p-1" />}>
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

const iconOf = (item: MailCategory): IconName =>
  item.name === AUTOMATED ? "automated" : item.name === CALENDAR ? "calendar" : item.mode === "exact" ? "folderRule" : "folderSmart";

/** Folders the person or an agent made. They live in the sidebar beside the fixed ones. `pick`
 *  chooses which: those the AI reads, or those it skips. A folder inside another shows by its
 *  own name, set in under its parent. */
export function CategoryNav({ collapsed, visibleHrefs, pick = (item) => !keptFromAi(item), label = t("nav.categories") }: { collapsed: boolean; visibleHrefs?: ReadonlySet<string>; pick?: (item: MailCategory) => boolean; label?: string }) {
  const categories = useCategories();
  const pathname = usePathname();
  if (collapsed) return null;
  const rows = customCategories(categories.data?.categories ?? []).filter((item) => pick(item) && (!visibleHrefs || visibleHrefs.has(categoryHref(item.name))));
  const names = new Set(rows.map((item) => item.name));
  return (
    <section aria-label={label}>
      <ul className="flex flex-col gap-px">
        {rows.map((item) => {
          const href = categoryHref(item.name);
          const parent = item.name.includes("/") ? item.name.slice(0, item.name.lastIndexOf("/")) : "";
          const nested = Boolean(parent) && names.has(parent);
          return (
            <li key={item.name} data-testid="nav-category">
              <FolderLink
                href={href}
                icon={iconOf(item)}
                tone={keptFromAi(item) ? "kept" : partlyKept(item) ? "partly" : "ai"}
                label={nested ? item.name.slice(parent.length + 1) : item.name}
                unread={item.unread ?? 0}
                active={isCurrentMail(pathname, href)}
                depth={nested ? 1 : 0}
                detail={[t(item.mode === "exact" ? "categories.kind.exact" : "categories.kind.smart"), ...(partlyKept(item) ? [t("nav.folder.partlyKept", { read: ((item.count ?? 0) - (item.kept ?? 0)).toLocaleString(), count: (item.count ?? 0).toLocaleString() })] : [])].join(". ")}
                menu={(link) => <MailNavMenu href={href} scope={{ folder: "all", category: item.name }} category={item}>{link}</MailNavMenu>}
                />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
