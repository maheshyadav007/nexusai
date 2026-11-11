import { describe, expect, it } from "vitest";
import { splitQuote } from "../ui/features/assistant/parts";

describe("splitQuote", () => {
  it("separates the quoted lines a message opens with", () => {
    expect(splitQuote("> The PLM release moves.\n>\n> QA signs off.\n\nWhat changes?")).toEqual({ quote: "The PLM release moves.\n\nQA signs off.", rest: "What changes?" });
  });

  it("leaves other messages alone, even with a > further in", () => {
    expect(splitQuote("Is 3 > 2?\n> not a quote")).toEqual({ quote: null, rest: "Is 3 > 2?\n> not a quote" });
    expect(splitQuote(">not quoted")).toEqual({ quote: null, rest: ">not quoted" });
  });
});
