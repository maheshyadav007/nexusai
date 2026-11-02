"use client";

import { createContext, use, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Icon } from "@/ui/icons";
import { t } from "@/ui/strings";
import { CitationMark } from "@/ui/primitives/Citation";
import { Pressable } from "@/ui/primitives/Pressable";
import type { MessageSource } from "./parts";

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    void navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_MS);
    });
  return (
    <div className="my-3 overflow-hidden rounded-md border border-line-subtle bg-surface-raised">
      <div className="flex items-center justify-between border-b border-line-subtle px-3 py-1 text-sm text-ink-muted">
        <span className="font-mono">{language}</span>
        <Pressable onClick={copy} className="inline-flex items-center gap-1 rounded-sm p-1 transition-colors duration-fast hover:text-ink-primary">
          <Icon name={copied ? "check" : "copy"} className="h-3 w-3" />
          {t(copied ? "chat.copied" : "chat.copy")}
        </Pressable>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-sm text-ink-primary">{children}</pre>
    </div>
  );
}

const COPIED_MS = 1500;

const textOf = (node: ReactNode): string => (Array.isArray(node) ? node.map(textOf).join("") : typeof node === "string" ? node : "");

const CITE = "#cite-";
const CitedSources = createContext<{ sources: readonly MessageSource[]; open: (source: MessageSource) => void } | null>(null);

function Cited({ number }: { number: string }) {
  const known = use(CitedSources);
  const source = known?.sources.find((item) => String(item.n) === number);
  return <CitationMark number={number} title={source?.title} label={t("chat.citation", { number })} onOpen={source && known ? () => known.open(source) : undefined} />;
}

const COMPONENTS: Components = {
  p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
  h1: ({ children }) => <h3 className="mb-2 mt-4 text-lg font-medium first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-2 mt-4 text-lg font-medium first:mt-0">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-3 font-medium first:mt-0">{children}</h4>,
  h4: ({ children }) => <h4 className="mb-1 mt-3 font-medium first:mt-0">{children}</h4>,
  ul: ({ children }) => <ul className="my-2 list-disc pl-5 marker:text-ink-faint">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal pl-5 marker:text-ink-muted">{children}</ol>,
  li: ({ children }) => <li className="my-1">{children}</li>,
  strong: ({ children }) => <strong className="font-medium">{children}</strong>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-line-strong pl-3 text-ink-secondary">{children}</blockquote>,
  hr: () => <hr className="my-4 border-line-subtle" />,
  a: ({ href, children }) => (href?.startsWith(CITE) ? <Cited number={href.slice(CITE.length)} /> : (
    <a href={href} target="_blank" rel="noreferrer noopener" className="focus-ring rounded-sm text-accent-default underline underline-offset-2">
      {children}
    </a>
  )),
  // A picture would load from wherever the model points, which could carry data out. It stays a link.
  img: ({ src, alt }) => (
    <a href={typeof src === "string" ? src : undefined} target="_blank" rel="noreferrer noopener" className="focus-ring rounded-sm text-accent-default underline underline-offset-2">
      {alt || t("chat.image")}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-md border border-line-subtle">
      <table className="w-full border-collapse text-left tabular-nums">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-line-subtle bg-surface-sunken px-3 py-2 font-medium">{children}</th>,
  td: ({ children }) => <td className="border-b border-line-subtle px-3 py-2 last:border-b-0">{children}</td>,
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
    const text = textOf(children);
    if (language || text.includes("\n")) return <CodeBlock language={language ?? t("chat.code")}>{text.replace(/\n$/, "")}</CodeBlock>;
    return <code className="rounded-sm bg-surface-sunken px-1 font-mono text-sm">{children}</code>;
  },
};

/** The model's words. Raw HTML in them is shown as text, never run. */
export function Markdown({ text, sources = [], onOpenSource }: { text: string; sources?: readonly MessageSource[]; onOpenSource?: (source: MessageSource) => void }) {
  return (
    <CitedSources value={{ sources, open: onOpenSource ?? (() => undefined) }}>
      <div className="break-words text-md text-ink-primary">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
          {text}
        </ReactMarkdown>
      </div>
    </CitedSources>
  );
}
