"use client";

import { useEffect, useRef, useState } from "react";
import { useSetSenderImages } from "@/ui/client/mail";
import { Button } from "@/ui/primitives/Button";
import { t } from "@/ui/strings";

const BLOCKED = /\ssrc=""\sdata-blocked-src="([^"]*)"/g;
// An empty src draws a broken-image icon, so blocked images get a clear pixel to sit behind.
const CLEAR_PIXEL = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

function document(html: string, showRemote: boolean, hideQuotes: boolean): string {
  const remote = showRemote ? " https: http:" : "";
  const policy = `default-src 'none'; img-src data:${remote}; style-src 'unsafe-inline'; font-src data:${remote}`;
  const body = html.replace(BLOCKED, showRemote ? ' src="$1"' : ` src="${CLEAR_PIXEL}" data-blocked-src="$1"`);
  // System colors, because mail is written for a light page whatever the app's theme. The font is
  // only for mail that doesn't choose one, and it comes first so the sender's styling wins.
  const css = `:root{color-scheme:light}html{overflow-x:auto;scrollbar-width:thin;scrollbar-color:color-mix(in srgb,CanvasText 40%,Canvas) transparent}body{margin:0;background:Canvas;color:CanvasText;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}img[data-blocked-src]{background:color-mix(in srgb,CanvasText 10%,Canvas);min-width:16px;min-height:16px}table{max-width:100%}${hideQuotes ? "blockquote,.gmail_quote,#divRplyFwdMsg{display:none}" : ""}`;
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${policy}"><base target="_blank"><style>${css}</style></head><body>${body}</body></html>`;
}

/** Mail HTML in a frame that can't run scripts, and loads nothing unless images are on. */
export function SafeMailFrame({ html, title, showImages = true, sender }: { html: string; title: string; showImages?: boolean; sender?: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const watcher = useRef<ResizeObserver | null>(null);
  const setSender = useSetSenderImages();
  const [showRemote, setShowRemote] = useState(showImages);
  const [showQuotes, setShowQuotes] = useState(false);
  useEffect(() => setShowRemote(showImages), [showImages]);
  useEffect(() => () => watcher.current?.disconnect(), []);
  const hasRemote = BLOCKED.test(html);
  BLOCKED.lastIndex = 0;
  const fit = () => {
    const node = frame.current;
    const height = node?.contentDocument?.documentElement.scrollHeight;
    if (node && height) node.style.height = `${height}px`;
  };
  // Images arrive after the frame says it's loaded, and each one can change its height.
  const follow = () => {
    fit();
    const inside = frame.current?.contentDocument;
    if (!inside) return;
    watcher.current?.disconnect();
    watcher.current = new ResizeObserver(fit);
    watcher.current.observe(inside.documentElement);
    for (const image of inside.images) image.addEventListener("load", fit);
  };
  return (
    <div className="flex flex-col gap-2">
      {hasRemote && !showRemote ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md bg-surface-sunken px-3 py-2 text-sm text-ink-secondary">
          {t("mail.remoteBlocked")}
          <Button variant="quiet" className="py-px" onClick={() => setShowRemote(true)}>
            {t("mail.remoteShow")}
          </Button>
          {sender ? (
            <Button variant="quiet" className="py-px" onClick={() => setSender.mutate({ address: sender, allow: true })}>
              {t("mail.remoteAlways")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {/* allow-same-origin only lets this page measure the frame. Without allow-scripts, nothing inside can run. */}
      <iframe ref={frame} title={title} sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" srcDoc={document(html, showRemote, !showQuotes)} onLoad={follow} className="w-full rounded-md border-0 bg-surface-raised" />
      <div className="flex flex-wrap gap-1">
        <Button variant="quiet" className="py-px" onClick={() => setShowQuotes((current) => !current)}>
          {t(showQuotes ? "mail.quotes.hide" : "mail.quotes.show")}
        </Button>
        {hasRemote && showRemote && sender ? (
          <Button variant="quiet" className="py-px" onClick={() => setSender.mutate({ address: sender, allow: false })}>
            {t("mail.remoteNever")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
