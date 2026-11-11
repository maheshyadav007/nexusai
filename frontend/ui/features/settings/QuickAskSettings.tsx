"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { desktopApi, type QuickAskChange, type QuickAskStatus } from "@/ui/client/desktop";
import { useLeadName } from "@/ui/client/home";
import { recordShortcut, shortcutKeys } from "@/ui/client/shortcut";
import { Button } from "@/ui/primitives/Button";
import { Card } from "@/ui/primitives/Card";
import { Kbd } from "@/ui/primitives/Kbd";
import { SettingRow } from "@/ui/primitives/SettingRow";
import { Switch } from "@/ui/primitives/Switch";
import { t, type StringKey } from "@/ui/strings";

const DEFAULT_SHORTCUT = "Control+Alt+Space";

/** The desktop app's quick-ask shortcut. Only the desktop app has one, so the browser shows nothing. */
export function QuickAskSettings() {
  const lead = useLeadName();
  const [status, setStatus] = useState<QuickAskStatus | null>(null);
  const [recording, setRecording] = useState(false);
  const [problem, setProblem] = useState<StringKey | null>(null);
  const quick = desktopApi()?.quick;

  useEffect(() => {
    void desktopApi()?.quick?.("status").then(setStatus).catch(() => {});
  }, []);
  // Coming back from System Settings, Accessibility may have been turned on.
  useEffect(() => {
    const read = () => void desktopApi()?.quick?.("status").then(setStatus).catch(() => {});
    window.addEventListener("focus", read);
    return () => window.removeEventListener("focus", read);
  }, []);
  if (!quick || !status) return null;

  const change = (value: QuickAskChange) => {
    setProblem(null);
    void quick("update", value).then((next) => {
      setStatus(next);
      if (next.error) setProblem(next.error === "taken" ? "quick.settings.taken" : "quick.settings.needsModifier");
    }).catch(() => setProblem("quick.settings.failed"));
  };
  const record = (event: KeyboardEvent) => {
    // The keys are the new shortcut, not the app's own, such as search on Ctrl+K.
    event.preventDefault();
    event.stopPropagation();
    const result = recordShortcut(event, status.platform);
    if ("cancelled" in result) { setRecording(false); setProblem(null); }
    else if ("needsModifier" in result) setProblem("quick.settings.needsModifier");
    else if ("shortcut" in result) { setRecording(false); change({ shortcut: result.shortcut }); }
  };

  return (
    <Card title={t("quick.settings.title")} description={t("quick.settings.description", { agent: lead })} aside={status.enabled ? <Button variant="secondary" onClick={() => void quick("open")}>{t("quick.settings.try")}</Button> : undefined}>
      <SettingRow label={t("quick.settings.enabled")}>
        <Switch label={t("quick.settings.enabled")} hideLabel checked={status.enabled} onChange={(enabled) => change({ enabled })} />
      </SettingRow>
      {status.enabled ? (
        <SettingRow label={t("quick.settings.shortcut")} {...(!status.registered ? { description: t("quick.settings.notHeld") } : {})} wide>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {recording ? (
              // Focused while it listens; a key press there becomes the shortcut.
              // eslint-disable-next-line jsx-a11y/no-autofocus
              <Button autoFocus variant="secondary" onKeyDown={record} onBlur={() => setRecording(false)}>{t("quick.settings.recording")}</Button>
            ) : (
              <>
                <span data-testid="quick-shortcut" className="flex items-center gap-1">{shortcutKeys(status.shortcut, status.platform).map((key) => <Kbd key={key}>{key}</Kbd>)}</span>
                <Button variant="quiet" onClick={() => { setProblem(null); setRecording(true); }}>{t("quick.settings.change")}</Button>
                {status.shortcut !== DEFAULT_SHORTCUT ? <Button variant="quiet" onClick={() => change({ shortcut: DEFAULT_SHORTCUT })}>{t("quick.settings.reset")}</Button> : null}
              </>
            )}
          </div>
        </SettingRow>
      ) : null}
      {problem ? <p role="alert" className="pb-3 text-sm text-status-danger">{t(problem)}</p> : null}
      {status.enabled ? (
        <SettingRow label={t("quick.settings.selection")} description={t("quick.settings.selection.hint")}>
          <Switch label={t("quick.settings.selection")} hideLabel checked={status.selection} onChange={(selection) => change({ selection })} />
        </SettingRow>
      ) : null}
      {status.enabled && status.selection && !status.selectionAllowed ? (
        <SettingRow label={t("quick.settings.allow")} description={t("quick.settings.allow.hint")}>
          <Button onClick={() => void quick("allow-selection").then(setStatus)}>{t("quick.settings.allow")}</Button>
        </SettingRow>
      ) : null}
    </Card>
  );
}
