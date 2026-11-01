"use client";

import { useState } from "react";
import { Button } from "@/ui/primitives/Button";
import { Dialog } from "@/ui/primitives/Dialog";
import { t } from "@/ui/strings";
import { Composer } from "./Composer";
import { MailList } from "./MailList";

export function NewMessage() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog title={t("mail.compose")} shape="drawer" open={open} onOpenChange={setOpen} trigger={<Button variant="primary">{t("mail.new")}</Button>}>
      <Composer initial={{}} onDone={() => setOpen(false)} />
    </Dialog>
  );
}

export function InboxScreen() {
  return <MailList title={t("nav.inbox")} folder="inbox" emptyIcon="inbox" emptyTitle="mail.empty.inbox" actions={<NewMessage />} />;
}

export function SentScreen() {
  return <MailList title={t("nav.sent")} folder="sent" emptyIcon="sent" emptyTitle="mail.empty.sent" showCategories={false} />;
}

export function CategoriesScreen() {
  return <MailList title={t("nav.categories")} folder="inbox" emptyIcon="categories" emptyTitle="mail.empty.inbox" />;
}
