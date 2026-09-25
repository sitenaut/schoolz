import type { ReactNode } from "react";

/** The small markdown subset the chatbot is told it may use
 * (services/chatbot.py:SYSTEM_PROMPT): **bold**, "- " bullets, "1. "
 * numbered lists, blank-line paragraph breaks, [text](url) links and bare
 * URLs. Anything else stays literal text.
 *
 * Deliberately hand-rolled into React elements rather than a markdown
 * library + dangerouslySetInnerHTML: the reply is model output built from
 * third-party data (event titles and descriptions scraped from other
 * sites), so it must never become markup. React escapes every string here;
 * the only attribute taken from the text is an href, and only http(s). */

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "hr" };

const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const NUMBERED_RE = /^\s*\d+[.)]\s+(.*)$/;
const RULE_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const last = () => blocks[blocks.length - 1];
  let breakBefore = true;
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      breakBefore = true;
      continue;
    }
    // A header the model slipped in anyway reads fine as a bold line.
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    const bullet = BULLET_RE.exec(line);
    const numbered = NUMBERED_RE.exec(line);
    if (RULE_RE.test(line)) {
      blocks.push({ kind: "hr" });
      breakBefore = true;
    } else if (bullet) {
      const prev = last();
      if (prev?.kind === "ul") prev.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
      breakBefore = false;
    } else if (numbered) {
      const prev = last();
      if (prev?.kind === "ol") prev.items.push(numbered[1]);
      else blocks.push({ kind: "ol", items: [numbered[1]] });
      breakBefore = false;
    } else {
      const content = heading ? `**${heading[1].replace(/\*\*/g, "")}**` : line;
      const prev = last();
      if (prev?.kind === "p" && !breakBefore && !heading) prev.lines.push(content);
      else blocks.push({ kind: "p", lines: [content] });
      // A heading always closes its own paragraph.
      breakBefore = Boolean(heading);
    }
  }
  return blocks;
}

// [text](http...) | **bold** | bare http(s) URL
const INLINE_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*(.+?)\*\*|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g;

export function renderInline(text: string, keyPrefix = ""): ReactNode[] {
  const out: ReactNode[] = [];
  let at = 0;
  let n = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const idx = m.index ?? 0;
    if (idx > at) out.push(text.slice(at, idx));
    const key = `${keyPrefix}${n++}`;
    if (m[1] !== undefined) {
      out.push(
        <a key={key} href={m[2]} target="_blank" rel="noopener noreferrer">
          {renderInline(m[1], `${key}.`)}
        </a>,
      );
    } else if (m[3] !== undefined) {
      out.push(<strong key={key}>{renderInline(m[3], `${key}.`)}</strong>);
    } else {
      out.push(
        <a key={key} href={m[4]} target="_blank" rel="noopener noreferrer">
          {m[4].replace(/^https?:\/\/(www\.)?/, "")}
        </a>,
      );
    }
    at = idx + m[0].length;
  }
  if (at < text.length) out.push(text.slice(at));
  return out;
}

export function ChatText({ text }: { text: string }) {
  return (
    <div className="chat-text">
      {parseBlocks(text).map((b, i) => {
        if (b.kind === "hr") return <hr key={i} />;
        if (b.kind === "p")
          return (
            <p key={i}>
              {b.lines.map((l, j) => (
                <span key={j}>
                  {j > 0 && <br />}
                  {renderInline(l, `${i}.${j}.`)}
                </span>
              ))}
            </p>
          );
        const List = b.kind;
        return (
          <List key={i}>
            {b.items.map((item, j) => (
              <li key={j}>{renderInline(item, `${i}.${j}.`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
