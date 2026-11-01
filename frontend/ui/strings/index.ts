import en from "./en.json";

export type StringKey = keyof typeof en;

export function t(key: StringKey, values?: Readonly<Record<string, string | number>>): string {
  const text: string = en[key];
  if (!values) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match));
}
