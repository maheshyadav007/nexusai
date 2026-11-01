"use client";

import { useState } from "react";
import type { IconName } from "@/ui/icons";
import { Avatar } from "@/ui/primitives/Avatar";
import { Badge } from "@/ui/primitives/Badge";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Checkbox } from "@/ui/primitives/Checkbox";
import { Dialog } from "@/ui/primitives/Dialog";
import { Divider } from "@/ui/primitives/Divider";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { ErrorState } from "@/ui/primitives/ErrorState";
import { Field } from "@/ui/primitives/Field";
import { IconButton } from "@/ui/primitives/IconButton";
import { Input, Textarea } from "@/ui/primitives/Input";
import { Kbd } from "@/ui/primitives/Kbd";
import { Menu } from "@/ui/primitives/Menu";
import { OfflineNotice } from "@/ui/primitives/OfflineNotice";
import { Popover } from "@/ui/primitives/Popover";
import { Progress } from "@/ui/primitives/Progress";
import { Select } from "@/ui/primitives/Select";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { StageBar } from "@/ui/primitives/StageBar";
import { StatusDot } from "@/ui/primitives/StatusDot";
import { Stepper } from "@/ui/primitives/Stepper";
import { Switch } from "@/ui/primitives/Switch";
import { Tabs } from "@/ui/primitives/Tabs";
import { TextLink } from "@/ui/primitives/TextLink";
import { useToast } from "@/ui/primitives/Toast";
import { Tooltip } from "@/ui/primitives/Tooltip";
import { AppearanceSettings } from "@/ui/features/settings/AppearanceSettings";
import { t } from "@/ui/strings";
import demo from "./fixtures/demo.json";

export function GalleryContent() {
  const toast = useToast();
  const [checked, setChecked] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [choice, setChoice] = useState(demo.options[0]?.value);
  const menu = demo.menu.map((item) => ({ ...item, icon: item.icon as IconName, onSelect: () => toast({ title: item.label }) }));
  return (
    <main className="mx-auto flex max-w-content flex-col gap-5 p-6">
      <header className="flex items-end justify-between gap-4">
        <h1 className="font-serif text-display text-ink-primary">{t("gallery.title")}</h1>
        <TextLink href="/gallery/shell">{t("gallery.shell")}</TextLink>
      </header>
      <AppearanceSettings />
      <Card title={t("gallery.actions")}>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">{t("gallery.sample.action")}</Button>
          <Button>{t("gallery.sample.action")}</Button>
          <Button variant="quiet">{t("gallery.sample.action")}</Button>
          <Button variant="danger">{t("gallery.sample.action")}</Button>
          <Button variant="primary" loading>
            {t("gallery.sample.action")}
          </Button>
          <Button disabled>{t("gallery.sample.action")}</Button>
          <IconButton icon="search" label={t("gallery.sample.action")} />
          <Kbd>{t("gallery.sample.key")}</Kbd>
          <TextLink href="/settings">{t("nav.settings")}</TextLink>
        </div>
      </Card>
      <Card title={t("gallery.forms")}>
        <div className="grid grid-cols-2 gap-4">
          <Field label={t("gallery.sample.label")} hint={t("gallery.sample.hint")}>
            {({ invalid, ...control }) => <Input invalid={invalid} placeholder={demo.email} {...control} />}
          </Field>
          <Field label={t("gallery.sample.label")} error={t("gallery.sample.error")}>
            {({ invalid, ...control }) => <Input invalid={invalid} defaultValue={demo.email} {...control} />}
          </Field>
          <Field label={t("gallery.sample.label")}>
            {({ invalid, ...control }) => <Input invalid={invalid} disabled defaultValue={demo.email} {...control} />}
          </Field>
          <Field label={t("gallery.sample.label")}>
            {({ invalid, id, "aria-describedby": describedBy }) => <Select id={id} invalid={invalid} {...(describedBy ? { describedBy } : {})} {...(choice ? { value: choice } : {})} options={demo.options} onChange={setChoice} />}
          </Field>
          <Field label={t("gallery.sample.label")}>
            {({ invalid, ...control }) => <Textarea invalid={invalid} rows={2} defaultValue={demo.person} {...control} />}
          </Field>
          <div className="flex flex-col gap-3">
            <Checkbox label={t("gallery.sample.label")} checked={checked} onChange={setChecked} />
            <Checkbox label={t("gallery.sample.disabled")} checked={false} disabled onChange={() => {}} />
            <Switch label={t("gallery.sample.label")} checked={enabled} onChange={setEnabled} />
            <Switch label={t("gallery.sample.disabled")} checked={false} disabled onChange={() => {}} />
          </div>
        </div>
      </Card>
      <Card title={t("gallery.overlays")}>
        <div className="flex flex-wrap items-center gap-3">
          <Dialog title={t("gallery.sample.title")} description={t("gallery.sample.hint")} trigger={<Button>{t("gallery.dialog")}</Button>}>
            <Button variant="primary">{t("gallery.sample.action")}</Button>
          </Dialog>
          <Dialog title={t("gallery.sample.title")} shape="drawer" trigger={<Button>{t("gallery.drawer")}</Button>}>
            <p className="text-md text-ink-secondary">{t("gallery.sample.hint")}</p>
          </Dialog>
          <Popover label={t("gallery.popover")} trigger={<Button>{t("gallery.popover")}</Button>}>
            <p className="text-md">{t("gallery.sample.hint")}</p>
          </Popover>
          <Menu trigger={<Button>{t("gallery.menu")}</Button>} items={menu} />
          <Tooltip content={t("gallery.sample.hint")}>
            <Button>{t("gallery.tooltip")}</Button>
          </Tooltip>
          <Button onClick={() => toast(demo.toast)}>{t("gallery.toast")}</Button>
          <Button onClick={() => toast({ title: t("gallery.sample.error"), tone: "danger" })}>{t("gallery.toast.error")}</Button>
        </div>
      </Card>
      <Card title={t("gallery.display")}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge>{t("gallery.sample.badge")}</Badge>
            <Badge tone="accent">{t("gallery.sample.badge")}</Badge>
            <Badge tone="success">{t("gallery.sample.badge")}</Badge>
            <Badge tone="warning">{t("gallery.sample.badge")}</Badge>
            <Badge tone="danger">{t("gallery.sample.badge")}</Badge>
            <Avatar name={demo.person} />
            <StatusDot tone="running" />
            <StatusDot tone="waiting" />
            <StatusDot tone="done" />
            <StatusDot tone="failed" />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <StageBar label={t("gallery.sample.label")} completed={0} />
            <StageBar label={t("gallery.sample.label")} completed={2} />
            <StageBar label={t("gallery.sample.label")} completed={4} />
            <StageBar label={t("gallery.sample.label")} completed={1} failed />
          </div>
          <Divider />
          <Stepper label={t("gallery.sample.label")} steps={demo.steps} current={1} />
          <Progress label={t("gallery.sample.label")} value={40} />
          <Tabs label={t("gallery.sample.label")} tabs={demo.tabs} />
        </div>
      </Card>
      <Card title={t("gallery.states")}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Skeleton />
            <Skeleton className="h-4 w-1/2" />
          </div>
          <EmptyState icon="inbox" title={t("gallery.sample.title")} description={t("gallery.sample.hint")} action={<Button>{t("gallery.sample.action")}</Button>} />
          <ErrorState title={t("error.title")} description={t("gallery.sample.error")} onRetry={() => {}} />
          <OfflineNotice message={t("connection.reconnecting")} />
        </div>
      </Card>
    </main>
  );
}
