import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { Modal } from "./ui/Modal";
import { ChatAvatar } from "./ChatAvatar";
import { IconSend } from "./icons";

type DisplayMessage = { role: "user" | "assistant"; text: string };
// Opaque role/content blocks exactly as the backend sent them back - never
// rendered directly (a tool_result block would show as if the user typed
// it), only replayed to /chat on the next turn so the model keeps context.
type ApiMessage = { role: string; content: unknown };

const GREETING = "Hi! Ask me about bell times, lunch menus, buses, or a school's calendar - anything on schoolz.";

/** The floating chat trigger + panel, mounted once in AppShell so it
 * persists across every route. A plain fixed-position button rather than
 * part of the page layout - see the placement writeup: a static bar (top
 * or bottom) would compete with the header and the mobile tab bar for
 * already-tight vertical space, where a FAB costs nothing until tapped. */
export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [apiHistory, setApiHistory] = useState<ApiMessage[]>([]);
  const [escalated, setEscalated] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, sending]);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", text }]);
    setSending(true);
    try {
      const r = await apiFetch("/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, history: apiHistory, escalated }),
      });
      if (r.status === 429) {
        const body = await r.json().catch(() => null);
        throw new Error(body?.detail || "Too many messages - please wait a few minutes and try again.");
      }
      if (!r.ok) throw new Error("Something went wrong - please try again.");
      const data = await r.json();
      setApiHistory(data.history);
      setEscalated(data.escalated);
      setMessages((m) => [...m, { role: "assistant", text: data.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong - please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <button className="chat-fab" onClick={() => setOpen(true)} aria-label="Ask schoolz">
        <ChatAvatar size={56} />
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title="Ask schoolz" subtitle="Answers pulled live from schoolz - never invented">
        <div className="chat-body">
          <div className="chat-scroll" ref={scrollRef}>
            <div className="chat-bubble assistant">{GREETING}</div>
            {messages.map((m, i) => (
              <div className={`chat-bubble ${m.role}`} key={i}>
                {m.text}
              </div>
            ))}
            {sending && (
              <div className="chat-bubble assistant chat-typing" aria-label="Thinking">
                <span />
                <span />
                <span />
              </div>
            )}
            {error && <div className="chat-error">{error}</div>}
          </div>
          <form
            className="chat-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <input
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about a school, bell times, lunch..."
              maxLength={2000}
              disabled={sending}
              autoFocus
            />
            <button className="btn btn-primary chat-send" type="submit" disabled={sending || !input.trim()} aria-label="Send">
              <IconSend />
            </button>
          </form>
        </div>
      </Modal>
    </>
  );
}
