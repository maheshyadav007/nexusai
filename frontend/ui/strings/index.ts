import en from "./en.json";

export type StringKey = keyof typeof en;

export function t(key: StringKey): string {
  return en[key];
}
