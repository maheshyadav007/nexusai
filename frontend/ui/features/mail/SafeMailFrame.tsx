"use client";

import { useRef, useState } from "react";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";

const BLOCKED = /\ssrc=""\sdata-blocked-src="([^"]*)"/g;

function document(html: string, showRemote: boolean, hideQuotes: boolean): string {
  const images = showRemote ? "img-src data: https: http:" : "img-src data:";
  const policy = `default-src 'none'; ${images}; style-src 'unsafe-inline'; font-src data:`;
  const body = showRemote ? html.replace(BLOCKED, ' src="$1"') : html;
  // System colors, because mail is written for a light page whatever the app's theme.
  const css = `:root{color-scheme:light}body{margin:0;background:Canvas;color:CanvasText;font-family:sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}${hideQuotes ? "blockquote,.gmail_quote,#divRplyFwdMsg{display:none}" : ""}`;
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><base target="_blank"><style>${css}</style></head><body>${body}</body></html>`;
}

/** Mail HTML in a frame that can't run scripts or load anything until asked. */
export function SafeMailFrame({ html, title }: { html: string; title: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [showRemote, setShowRemote] = useState(false);
  const [showQuotes, setShowQuotes] = useState(false);
  const hasRemote = BLOCKED.test(html);
  BLOCKED.lastIndex = 0;
  const fit = () => {
    const node = frame.current;
    const height = node?.contentDocument?.documentElement.scrollHeight;
    if (node && height) node.style.height = `${height}px`;
  };
  return (
    <div className="flex flex-col gap-2">
      {hasRemote && !showRemote ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md bg-surface-sunken px-3 py-2 text-sm text-ink-secondary">
          {t("mail.remoteBlocked")}
          <Button variant="quiet" className="py-px" onClick={() => setShowRemote(true)}>
            {t("mail.remoteShow")}
          </Button>
        </div>
      ) : null}
      {/* allow-same-origin only lets this page measure the frame. Without allow-scripts, nothing inside can run. */}
      <iframe ref={frame} title={title} sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" srcDoc={document(html, showRemote, !showQuotes)} onLoad={fit} className="w-full rounded-md border border-line-subtle" />
      <div>
        <Button variant="quiet" className="py-px" onClick={() => setShowQuotes((current) => !current)}>
          {t(showQuotes ? "mail.quotes.hide" : "mail.quotes.show")}
        </Button>
      </div>
    </div>
  );
}
