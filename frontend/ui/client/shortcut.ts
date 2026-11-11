// Shortcuts in Electron's accelerator form, such as "Control+Alt+Space": read from a key press
// in Settings, and shown back as the keys on the person's keyboard.

const NAMED: Readonly<Record<string, string>> = {
  Space: "Space", Enter: "Enter", Tab: "Tab", Backspace: "Backspace", Delete: "Delete", Insert: "Insert",
  Home: "Home", End: "End", PageUp: "PageUp", PageDown: "PageDown",
  ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right",
  Minus: "-", Equal: "=", BracketLeft: "[", BracketRight: "]", Backslash: "\\", Semicolon: ";",
  Quote: "'", Comma: ",", Period: ".", Slash: "/", Backquote: "`",
};

interface KeyPress { code: string; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }

/** The key itself, by where it sits, so Option or Shift changing the letter doesn't matter. */
function keyOf(code: string): string | null {
  const letter = /^Key([A-Z])$/.exec(code)?.[1];
  if (letter) return letter;
  const digit = /^(?:Digit|Numpad)([0-9])$/.exec(code)?.[1];
  if (digit) return digit;
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  return NAMED[code] ?? null;
}

export type Recorded = { shortcut: string } | { waiting: true } | { cancelled: true } | { needsModifier: true };

/** What one key press in the shortcut field means. Escape on its own gives up. */
export function recordShortcut(press: KeyPress, platform: string): Recorded {
  const modifiers = [
    ...(press.ctrlKey ? ["Control"] : []),
    ...(press.altKey ? ["Alt"] : []),
    ...(press.shiftKey ? ["Shift"] : []),
    ...(press.metaKey ? [platform === "darwin" ? "Command" : "Super"] : []),
  ];
  if (press.code === "Escape" && !modifiers.length) return { cancelled: true };
  const key = keyOf(press.code);
  if (!key) return { waiting: true };
  if (!modifiers.some((modifier) => modifier !== "Shift")) return { needsModifier: true };
  return { shortcut: [...modifiers, key].join("+") };
}

const MAC: Readonly<Record<string, string>> = { Control: "⌃", Alt: "⌥", Shift: "⇧", Command: "⌘", Super: "⌘" };
const OTHER: Readonly<Record<string, string>> = { Control: "Ctrl", Alt: "Alt", Shift: "Shift", Command: "Win", Super: "Win" };

/** The keys to show, one per key cap. */
export function shortcutKeys(shortcut: string, platform: string): string[] {
  const names = platform === "darwin" ? MAC : OTHER;
  return shortcut.split("+").map((part) => names[part] ?? part);
}
