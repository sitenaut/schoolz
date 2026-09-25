import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChatText, parseBlocks } from "./chatFormat";

const html = (text: string) => renderToStaticMarkup(<ChatText text={text} />);

describe("parseBlocks", () => {
  it("groups an events answer into a bold day line and a bullet list per day", () => {
    const blocks = parseBlocks(
      "Here's what's on:\n\n**Saturday, Oct 3**\n- 10:00 AM · Fall Festival · Croft Farm\n- 2:00 PM · Story Time\n\n**Sunday, Oct 4**\n- Noon · 5K",
    );
    expect(blocks.map((b) => b.kind)).toEqual(["p", "p", "ul", "p", "ul"]);
    expect(blocks[2]).toEqual({ kind: "ul", items: ["10:00 AM · Fall Festival · Croft Farm", "2:00 PM · Story Time"] });
  });

  it("keeps single newlines inside a paragraph as line breaks", () => {
    expect(parseBlocks("Line one\nLine two")).toEqual([{ kind: "p", lines: ["Line one", "Line two"] }]);
  });

  it("a bold line starting with ** is not mistaken for a '*' bullet", () => {
    expect(parseBlocks("**Saturday**")[0].kind).toBe("p");
  });

  it("numbered lists and rules", () => {
    expect(parseBlocks("1. First\n2. Second\n---\nAfter").map((b) => b.kind)).toEqual(["ol", "hr", "p"]);
  });
});

describe("ChatText", () => {
  it("renders bold, markdown links, and bare URLs", () => {
    const out = html("- 10 AM · [Fall Festival](https://example.com/fest) · **free**\nSee https://www.example.org/x.");
    expect(out).toContain('<a href="https://example.com/fest" target="_blank" rel="noopener noreferrer">Fall Festival</a>');
    expect(out).toContain("<strong>free</strong>");
    // Trailing sentence punctuation isn't swallowed into the URL.
    expect(out).toContain('href="https://www.example.org/x"');
    expect(out).toContain(">example.org/x</a>.");
  });

  it("never turns text into markup, and only links http(s)", () => {
    const out = html('<img src=x onerror=alert(1)> [click](javascript:alert(1))');
    expect(out).not.toContain("<img");
    expect(out).not.toContain('href="javascript');
    expect(out).toContain("&lt;img");
  });

  it("a header the model slipped in renders as a bold line, not a literal #", () => {
    expect(html("## This weekend\nStuff")).toBe("<div class=\"chat-text\"><p><span><strong>This weekend</strong></span></p><p><span>Stuff</span></p></div>");
  });
});
