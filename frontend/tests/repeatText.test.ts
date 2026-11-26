import { describe, expect, it } from "vitest";
import type { Reminder } from "../ui/client/contracts.generated";
import { repeatText } from "../ui/features/planner/repeatText";

const base: Reminder = { id: 1, title: "Drink water", when: "2031-06-02T10:00", repeat: "interval", thread: null, task: null, source: "agent", proposed: false, fired: false };
const day = (value: string) => `[${value}]`;

describe("how a reminder repeats, in words", () => {
  it("says the drink-water rule as the mockup does", () => {
    expect(repeatText({ ...base, every_minutes: 60, days: [0, 1, 2, 3, 4], window_start: "10:00", window_end: "20:00" }, day)).toBe("Every hour, 10:00–20:00, Mon–Fri");
  });
  it("counts hours and minutes, names odd days and the end date", () => {
    expect(repeatText({ ...base, every_minutes: 120, days: [5, 6] }, day)).toBe("Every 2 hours, Weekends");
    expect(repeatText({ ...base, every_minutes: 30, days: [0, 2], until: "2031-12-31" }, day)).toBe("Every 30 minutes, Mon and Wed, until [2031-12-31]");
  });
  it("keeps the old words for the old repeats", () => {
    expect(repeatText({ ...base, repeat: "week" }, day)).toBe("Every week");
    expect(repeatText({ ...base, repeat: "none" }, day)).toBe("Doesn't repeat");
  });
});
