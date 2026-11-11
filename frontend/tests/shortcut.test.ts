import { describe, expect, it } from "vitest";
import { recordShortcut, shortcutKeys } from "../ui/client/shortcut";

const press = (code: string, keys: Partial<{ ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }> = {}) =>
  ({ code, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...keys });

describe("recordShortcut", () => {
  it("reads modifiers and the key by its place on the keyboard", () => {
    expect(recordShortcut(press("Space", { ctrlKey: true, altKey: true }), "win32")).toEqual({ shortcut: "Control+Alt+Space" });
    expect(recordShortcut(press("KeyP", { metaKey: true, shiftKey: true }), "darwin")).toEqual({ shortcut: "Shift+Command+P" });
    expect(recordShortcut(press("KeyP", { metaKey: true }), "win32")).toEqual({ shortcut: "Super+P" });
    expect(recordShortcut(press("Slash", { ctrlKey: true }), "linux")).toEqual({ shortcut: "Control+/" });
    expect(recordShortcut(press("F5", { altKey: true }), "win32")).toEqual({ shortcut: "Alt+F5" });
  });

  it("waits while only modifiers are down, and asks for one when there is none", () => {
    expect(recordShortcut(press("ControlLeft", { ctrlKey: true }), "win32")).toEqual({ waiting: true });
    expect(recordShortcut(press("KeyA"), "win32")).toEqual({ needsModifier: true });
    expect(recordShortcut(press("KeyA", { shiftKey: true }), "win32")).toEqual({ needsModifier: true });
  });

  it("gives up on Escape alone", () => {
    expect(recordShortcut(press("Escape"), "darwin")).toEqual({ cancelled: true });
  });
});

describe("shortcutKeys", () => {
  it("shows the keys as the keyboard names them", () => {
    expect(shortcutKeys("Control+Alt+Space", "win32")).toEqual(["Ctrl", "Alt", "Space"]);
    expect(shortcutKeys("Control+Alt+Space", "darwin")).toEqual(["⌃", "⌥", "Space"]);
    expect(shortcutKeys("Super+P", "win32")).toEqual(["Win", "P"]);
  });
});
