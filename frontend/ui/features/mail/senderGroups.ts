import type { SortSender } from "@/ui/client/contracts.generated";

/** Senders in one card that belong together, so a whole group moves in one press. */
export interface SenderGroup {
  key: string;
  name: string;
  members: SortSender[];
  count: number;
}

// Words in an address that say nothing about what it sends.
const NOISE = new Set(["no", "noreply", "reply", "do", "not", "donotreply", "mail", "email", "mailer", "info"]);
// Two words this alike are one: "jobs" and "jobalerts", "messages" and "messaging". They share a
// start, and differ by no more than an ending.
const SAME_START = 3;
const ENDING = 3;
// What sits before a country's ending, as in amazon.co.uk or irctc.gov.in.
const SECOND_LEVEL = new Set(["co", "com", "net", "org", "gov", "ac", "edu", "ne", "or"]);

/** The name a domain is registered under, with what's before it: mail.amazon.jobs gives
 *  amazon.jobs, amazon.co.uk stays whole. */
export function siteOf(domain: string): string {
  const labels = domain.toLowerCase().split(".");
  const keep = labels.length >= 3 && SECOND_LEVEL.has(labels[labels.length - 2] ?? "") ? 3 : 2;
  return labels.slice(-keep).join(".");
}

const wordsOf = (sender: string) => (sender.split("@")[0] ?? "").toLowerCase().split(/[^a-z]+/).filter((word) => word.length >= 2 && !NOISE.has(word));
const alike = (a: string, b: string) => {
  let same = 0;
  while (same < a.length && a[same] === b[same]) same += 1;
  return a === b || (same >= SAME_START && same >= Math.min(a.length, b.length) - ENDING);
};

/** One card's senders in groups, biggest first. Senders from different sites split by site;
 *  under one site, senders join when a word before the @ is alike. */
export function groupSenders(senders: readonly SortSender[]): SenderGroup[] {
  const bySite = Map.groupBy(senders, (s) => siteOf(s.sender.split("@")[1] ?? ""));
  const groups: { name: string; members: SortSender[] }[] = bySite.size > 1
    ? [...bySite.entries()].map(([site, members]) => ({ name: site, members }))
    : byWords(senders);
  return groups
    .map(({ name, members }) => {
      const sorted = [...members].sort((a, b) => b.count - a.count);
      return { key: sorted.map((s) => s.sender).join(" "), name: sorted.length === 1 ? (sorted[0] as SortSender).sender : name, members: sorted, count: sorted.reduce((n, s) => n + s.count, 0) };
    })
    .sort((a, b) => b.count - a.count);
}

function byWords(senders: readonly SortSender[]): { name: string; members: SortSender[] }[] {
  const words = senders.map((s) => wordsOf(s.sender));
  const parent = senders.map((_, index) => index);
  const find = (i: number): number => (parent[i] === i ? i : (parent[i] = find(parent[i] as number)));
  for (let i = 0; i < senders.length; i += 1)
    for (let j = i + 1; j < senders.length; j += 1)
      if ((words[i] ?? []).some((a) => (words[j] ?? []).some((b) => alike(a, b)))) parent[find(j)] = find(i);
  const joined = Map.groupBy(senders.map((_, index) => index), find);
  return [...joined.values()].map((indexes) => {
    const members = indexes.map((index) => senders[index] as SortSender);
    // The word every member shares, else the shortest first word: "jobs" for jobs- and jobalerts-.
    const lists = indexes.map((index) => words[index] ?? []);
    const shared = (lists[0] ?? []).find((word) => lists.every((list) => list.includes(word)));
    const first = lists.map((list) => list[0]).filter((word): word is string => Boolean(word)).sort((a, b) => a.length - b.length)[0];
    return { name: shared ?? first ?? members[0]?.sender ?? "", members };
  });
}
