import { trackEvent } from "../lib/track";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { Modal } from "./ui/Modal";
import { ChatAvatar } from "./ChatAvatar";
import { ChatText } from "../lib/chatFormat";
import { IconSend } from "./icons";
import { useTranslation } from "react-i18next";

type DisplayMessage = { role: "user" | "assistant"; text: string };
// Opaque role/content blocks exactly as the backend sent them back - never
// rendered directly (a tool_result block would show as if the user typed
// it), only replayed to /chat on the next turn so the model keeps context.
type ApiMessage = { role: string; content: unknown };

/** The floating chat trigger + panel, mounted once in AppShell so it
 * persists across every route. A plain fixed-position button rather than
 * part of the page layout - see the placement writeup: a static bar (top
 * or bottom) would compete with the header and the mobile tab bar for
 * already-tight vertical space, where a FAB costs nothing until tapped. */
export function ChatWidget() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const greeting = user
    ? t("Hi! Ask me about your kids - what's due or missing, grades, today's schedule - what's on this weekend, or anything else on schoolz.")
    : t("Hi! Ask me about bell times, lunch menus, buses, or a school's calendar - anything on schoolz.");
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [apiHistory, setApiHistory] = useState<ApiMessage[]>([]);
  const [escalated, setEscalated] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // The backend offers personal tools per request based on the login, so a
  // transcript from before a sign-in/out would carry one account's kids'
  // data into the next account's conversation. Start over instead.
  const userId = user?.id ?? null;
  useEffect(() => {
    setMessages([]);
    setApiHistory([]);
    setEscalated(false);
    setError(null);
  }, [userId]);

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
    trackEvent("chat_message_sent", { turn: apiHistory.length + 1 });
    try {
      const r = await apiFetch("/chat", {
        method: "POST",
        body: JSON.stringify({ message: text, history: apiHistory, escalated }),
      });
      if (r.status === 429) {
        const body = await r.json().catch(() => null);
        throw new Error(body?.detail || t("Too many messages - please wait a few minutes and try again."));
      }
      if (!r.ok) throw new Error(t("Something went wrong - please try again."));
      const data = await r.json();
      setApiHistory(data.history);
      setEscalated(data.escalated);
      setMessages((m) => [...m, { role: "assistant", text: data.reply }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Something went wrong - please try again."));
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <button
        className="chat-fab"
        onClick={() => {
          setOpen(true);
          trackEvent("chat_opened");
        }}
        aria-label={t("Ask schoolz")}
      >
        <ChatAvatar size={56} />
      </button>

      <Modal open={open} onClose={() => setOpen(false)} title={t("Ask schoolz")} subtitle={t("Answers pulled live from schoolz - never invented")}>
        <div className="chat-body">
          <div className="chat-scroll" ref={scrollRef}>
            <div className="chat-bubble assistant">{greeting}</div>
            {messages.map((m, i) => (
              <div className={`chat-bubble ${m.role}`} key={i}>
                {m.role === "assistant" ? <ChatText text={m.text} /> : m.text}
              </div>
            ))}
            {sending && (
              <div className="chat-bubble assistant chat-typing" aria-label={t("Thinking")}>
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
              placeholder={user ? t("What's due tomorrow? Any missing work?") : t("Ask about a school, bell times, lunch...")}
              maxLength={2000}
              disabled={sending}
              autoFocus
            />
            <button className="btn btn-primary chat-send" type="submit" disabled={sending || !input.trim()} aria-label={t("Send")}>
              <IconSend />
            </button>
          </form>
        </div>
      </Modal>
    </>
  );
}
