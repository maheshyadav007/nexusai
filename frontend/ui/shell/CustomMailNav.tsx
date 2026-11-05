"use client";

import { useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useCategories, useMailFolders } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";
import { CategoryNav } from "./CategoryNav";
import { FolderNav } from "./FolderNav";
import { categoryHref, customCategories, customFolders, CUSTOM_MAIL_PREVIEW, folderHref, previewMailHrefs } from "./customMail";

export function CustomMailNav({ collapsed }: { collapsed: boolean }) {
  const categories = useCategories();
  const folders = useMailFolders();
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const hrefs = [
    ...customCategories(categories.data?.categories ?? []).map((item) => categoryHref(item.name)),
    ...customFolders(folders.data?.folders ?? [], pathname).map((item) => folderHref(item.name)),
  ];
  if (collapsed || !hrefs.length) return null;
  const visibleHrefs = expanded ? undefined : previewMailHrefs(hrefs, pathname);
  return (
    <div className="my-1 flex shrink-0 flex-col">
      <div ref={list} id={id} className="category-scroll max-h-folder-list overflow-y-auto overscroll-contain" tabIndex={0} role="region" aria-label={t("nav.customMail")}>
        <CategoryNav collapsed={false} visibleHrefs={visibleHrefs} />
        <FolderNav collapsed={false} visibleHrefs={visibleHrefs} />
      </div>
      {hrefs.length > CUSTOM_MAIL_PREVIEW ? (
        <Button variant="quiet" aria-expanded={expanded} aria-controls={id} className="mt-1 shrink-0 self-start px-2 py-1 text-sm" onClick={() => {
          setExpanded(!expanded);
          list.current?.scrollTo({ top: 0 });
        }}>
          {t(expanded ? "nav.folders.showLess" : "nav.folders.showAll", { count: hrefs.length })}
        </Button>
      ) : null}
    </div>
  );
}
