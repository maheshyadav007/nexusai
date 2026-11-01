import en from "./en.json";

export type StringKey = keyof typeof en;

type PluralKey = { [K in StringKey]: K extends `${infer Base}.one` ? Base : never }[StringKey];

/** Picks ".one" or ".other", and writes the count with this person's digit grouping. */
export function tn(key: PluralKey, count: number, values?: Readonly<Record<string, string | number>>): string {
  return t(`${key}.${count === 1 ? "one" : "other"}` as StringKey, { ...values, count: count.toLocaleString() });
}

export function t(key: StringKey, values?: Readonly<Record<string, string | number>>): string {
  const text: string = en[key];
  if (!values) return text;
  return text.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match));
}
