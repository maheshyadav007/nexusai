"use client";

import { useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useCategories } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";
import { CategoryNav } from "./CategoryNav";
import { categoryHref, customCategories, CUSTOM_MAIL_PREVIEW, keptFromAi, previewMailHrefs } from "./customMail";
import { useHiddenFolders } from "./hiddenFolders";

/** The person's own folders, rule and smart alike: the first few, and the rest on request. */
export function CustomMailNav({ collapsed, after }: { collapsed: boolean; after?: React.ReactNode }) {
  const categories = useCategories();
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const { hidden } = useHiddenFolders();
  const own = customCategories(categories.data?.categories ?? []).filter((item) => !keptFromAi(item));
  const hrefs = own.map((item) => categoryHref(item.name));
  // What's hidden waits under Show all, unless it's the one open.
  const showing = own.filter((item) => !hidden.has(item.name)).map((item) => categoryHref(item.name));
  if (collapsed) return null;
  // The server's labels follow the person's folders, before the button that shows the rest.
  if (!hrefs.length) return after ? <div className="flex shrink-0 flex-col">{after}</div> : null;
  const open = hrefs.find((href) => pathname === href || pathname.startsWith(`${href}/`));
  const visibleHrefs = expanded ? undefined : previewMailHrefs(open && !showing.includes(open) ? [...showing, open] : showing, pathname);
  return (
    <div className="flex shrink-0 flex-col">
      <div ref={list} id={id} className="category-scroll max-h-folder-list overflow-y-auto overscroll-contain" tabIndex={0} role="region" aria-label={t("nav.customMail")}>
        <CategoryNav collapsed={false} visibleHrefs={visibleHrefs} />
      </div>
      {after}
      {showing.length > CUSTOM_MAIL_PREVIEW || showing.length < hrefs.length ? (
        <Button variant="quiet" aria-expanded={expanded} aria-controls={id} className="shrink-0 self-start px-2 py-1 text-sm" onClick={() => {
          setExpanded(!expanded);
          list.current?.scrollTo({ top: 0 });
        }}>
          {t(expanded ? "nav.folders.showLess" : "nav.folders.showAll", { count: hrefs.length })}
        </Button>
      ) : null}
    </div>
  );
}
