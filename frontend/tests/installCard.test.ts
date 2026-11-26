import { describe, expect, it } from "vitest";
import type { UIMessage } from "ai";
import { installedName, toBlocks, type ToolPart } from "../ui/features/assistant/parts";

const tool = (name: string, output: unknown, state = "output-available"): ToolPart => ({ type: `tool-${name}`, toolCallId: `${name}-1`, state, input: {}, output });

describe("the install card", () => {
  it("shows for a plugin the tool says it installed", () => {
    expect(installedName(tool("propose_plugin", "Installed plugin mcp-server-dev. On now: build-mcp-app. Tell the person in a sentence."))).toBe("mcp-server-dev");
    expect(installedName(tool("create_plugin", "Created it in /Home/plugins/plm-triage. Installed plugin plm-triage. Tell the person in a sentence."))).toBe("plm-triage");
  });

  it("stays in the trace while asking, on a failure, and for other tools", () => {
    expect(installedName(tool("propose_plugin", "Waiting for the person to approve installing x."))).toBeNull();
    expect(installedName(tool("propose_plugin", "Installed plugin x. ", "output-error"))).toBeNull();
    expect(installedName(tool("search_mail", "Installed plugin x. "))).toBeNull();
  });

  it("makes a card block instead of a trace step", () => {
    const message = { id: "m", role: "assistant", parts: [tool("propose_plugin", "Installed plugin x. Tell the person in a sentence.")] } as unknown as UIMessage;
    expect(toBlocks(message, new Set()).map((block) => block.kind)).toEqual(["card"]);
  });
});
