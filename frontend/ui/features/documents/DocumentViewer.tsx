"use client";

import { useState } from "react";
import type { DocumentReader } from "@/ui/client/contracts.generated";
import { Markdown } from "@/ui/features/assistant/Markdown";
import { SafeMailFrame } from "@/ui/features/mail/SafeMailFrame";
import { CodeView } from "@/ui/primitives/CodeView";
import { EmptyState } from "@/ui/primitives/EmptyState";
import { TableView } from "@/ui/primitives/TableView";
import { Tabs } from "@/ui/primitives/Tabs";
import { t } from "@/ui/strings";

const SHEET_MARK = /^\[Sheet: (.*)\]$/;
// A browser slows down badly past this many table rows, and the file is there to download.
const MOST_ROWS = 2000;

interface Sheet {
  name: string;
  rows: string[][];
}

function sheetsOf(text: string, fallback: string): Sheet[] {
  const sheets: Sheet[] = [];
  for (const line of text.split("\n")) {
    const mark = SHEET_MARK.exec(line);
    if (mark) {
      sheets.push({ name: mark[1] ?? "", rows: [] });
      continue;
    }
    if (!line.trim()) continue;
    if (!sheets.length) sheets.push({ name: fallback, rows: [] });
    sheets[sheets.length - 1]?.rows.push(line.split("\t"));
  }
  return sheets;
}

function Spreadsheet({ text, name }: { text: string; name: string }) {
  const sheets = sheetsOf(text, name);
  const [first] = sheets;
  if (!first) return <EmptyState icon="documents" title={t("documents.noText")} />;
  const table = (sheet: Sheet) => (
    <div className="flex flex-col gap-2">
      <TableView label={sheet.name} rows={sheet.rows.slice(0, MOST_ROWS)} />
      {sheet.rows.length > MOST_ROWS ? <p className="text-sm text-ink-muted">{t("reader.moreRows", { shown: MOST_ROWS, total: sheet.rows.length })}</p> : null}
    </div>
  );
  if (sheets.length === 1) return table(first);
  return <Tabs label={name} tabs={sheets.map((sheet) => ({ value: sheet.name, label: sheet.name, content: table(sheet) }))} />;
}

function Picture({ src, name }: { src: string; name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <EmptyState icon="documents" title={t("reader.pictureFailed")} />;
  // eslint-disable-next-line @next/next/no-img-element -- it comes from the local backend, not the web
  return <img src={src} alt={name} onError={() => setFailed(true)} className="max-w-full rounded-md" />;
}

/** One door for showing a file: each kind the way it reads best. */
export function DocumentViewer({ reader }: { reader: DocumentReader }) {
  const inline = `${reader.url}&inline=true`;
  if (reader.kind === "pdf") return <iframe data-testid="pdf-frame" title={reader.name} src={inline} className="h-screen w-full rounded-md border border-line-subtle" />;
  if (reader.kind === "image") return <Picture src={inline} name={reader.name} />;
  if (reader.html) return <SafeMailFrame html={reader.html} title={reader.name} />;
  if (!reader.text) return <EmptyState icon="documents" title={reader.status_reason ?? t("documents.noText")} />;
  if (reader.kind === "table") return <Spreadsheet text={reader.text} name={reader.name} />;
  if (reader.kind === "code") return <CodeView label={reader.name} text={reader.text} />;
  // Word, PowerPoint and the like come out as markdown, and read best at this width.
  return (
    <article data-testid="reader-text" className="mx-auto w-full max-w-reading">
      <Markdown text={reader.text} />
    </article>
  );
}
