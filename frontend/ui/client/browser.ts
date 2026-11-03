// Browsers only offer some features on https or localhost, and this app can be opened by IP.

export function newId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const box = document.createElement("textarea");
  box.value = text;
  // Inside an open dialog, focus can't leave it, so it goes where the focus already is.
  (document.activeElement?.closest("[role=dialog]") ?? document.body).appendChild(box);
  box.select();
  const copied = document.execCommand("copy");
  box.remove();
  if (!copied) throw new Error("Couldn't copy");
}
