import { describe, expect, it } from "vitest";
import type { SortSender } from "../ui/client/contracts.generated";
import { groupSenders, siteOf } from "../ui/features/mail/senderGroups";

const sender = (address: string, count: number) => ({ sender: address, count }) as SortSender;
const named = (groups: ReturnType<typeof groupSenders>) => groups.map((group) => [group.name, group.members.map((s) => s.sender.split("@")[0]), group.count]);

describe("groupSenders", () => {
  it("joins senders of one site whose words before the @ are alike", () => {
    const linkedin = [
      sender("jobalerts-noreply@linkedin.com", 195),
      sender("inmail-hit-reply@linkedin.com", 34),
      sender("jobs-noreply@linkedin.com", 9),
      sender("messaging-digest-noreply@linkedin.com", 9),
      sender("messages-noreply@linkedin.com", 7),
      sender("groups-noreply@linkedin.com", 6),
      sender("hit-reply@linkedin.com", 5),
      sender("notifications-noreply@linkedin.com", 3),
    ];
    expect(named(groupSenders(linkedin))).toEqual([
      ["jobs", ["jobalerts-noreply", "jobs-noreply"], 204],
      ["hit", ["inmail-hit-reply", "hit-reply"], 39],
      ["messages", ["messaging-digest-noreply", "messages-noreply"], 16],
      ["groups-noreply@linkedin.com", ["groups-noreply"], 6],
      ["notifications-noreply@linkedin.com", ["notifications-noreply"], 3],
    ]);
  });

  it("splits a card by site, so a company's jobs mail is apart from its shop", () => {
    const amazon = [
      sender("noreply@mail.amazon.jobs", 33),
      sender("store-news@amazon.in", 33),
      sender("return@amazon.in", 29),
      sender("noreply@portal-na.idprism-auth.amazon.dev", 3),
    ];
    expect(named(groupSenders(amazon))).toEqual([
      ["amazon.in", ["store-news", "return"], 62],
      ["noreply@mail.amazon.jobs", ["noreply"], 33],
      ["noreply@portal-na.idprism-auth.amazon.dev", ["noreply"], 3],
    ]);
  });

  it("keeps a country's ending with the name", () => {
    expect([siteOf("mail.amazon.jobs"), siteOf("amazon.co.uk"), siteOf("alerts.irctc.gov.in"), siteOf("m.parallels.com")]).toEqual(["amazon.jobs", "amazon.co.uk", "irctc.gov.in", "parallels.com"]);
  });
});
