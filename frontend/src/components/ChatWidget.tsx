import { trackEvent } from "../lib/track";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { Modal } from "./ui/Modal";
import { ChatAvatar } from "./ChatAvatar";
import { ChatText, toPlainText } from "../lib/chatFormat";
import { IconCheck, IconCopy, IconRefresh, IconSend, IconShare } from "./icons";
import { useTranslation } from "react-i18next";

type DisplayMessage = { role: "user" | "assistant"; text: string };
// Opaque role/content blocks exactly as the backend sent them back - never
// rendered directly (a tool_result block would show as if the user typed
// it), only replayed to /chat on the next turn so the model keeps context.
type ApiMessage = { role: string; content: unknown };

// The conversation survives a reload for the rest of the visit, not
// longer: sessionStorage is per tab and gone when it closes. It's tagged
// with the account it belongs to and dropped when that changes, for the
// same reason the transcript is reset on sign-in/out below.
const STORE_KEY = "schoolz_chat_v1";
type Saved = { userId: string | number | null; messages: DisplayMessage[]; apiHistory: ApiMessage[]; escalated: boolean };

function loadSaved(userId: Saved["userId"]): Saved | null {
  try {
    const s = JSON.parse(sessionStorage.getItem(STORE_KEY) ?? "null") as Saved | null;
    if (s && s.userId === userId && Array.isArray(s.messages) && Array.isArray(s.apiHistory)) return s;
    sessionStorage.removeItem(STORE_KEY);
  } catch {
    // Storage blocked or a bad value: start fresh.
  }
  return null;
}

function save(s: Saved) {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(s));
  } catch {
    // Full or blocked - the chat still works, it just won't survive a reload.
  }
}

const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

/** The floating chat trigger + panel, mounted once in AppShell so it
 * persists across every route. A plain fixed-position button rather than
 * part of the page layout - see the placement writeup: a static bar (top
 * or bottom) would compete with the header and the mobile tab bar for
 * already-tight vertical space, where a FAB costs nothing until tapped. */
export function ChatWidget() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
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
  const [copied, setCopied] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Moves whenever the transcript is reset (sign-in/out, New chat), so a
  // reply still in flight from before can tell it no longer belongs here.
  const conversation = useRef(0);

  // The backend offers personal tools per request based on the login, so a
  // transcript from before a sign-in/out would carry one account's kids'
  // data into the next account's conversation. Start over instead - unless
  // the saved one is this same account's (a reload). Wait for auth to settle
  // so a signed-in reload doesn't briefly look anonymous and drop it.
  const userId = user?.id ?? null;
  useEffect(() => {
    if (loading) return;
    conversation.current += 1;
    const s = loadSaved(userId);
    setMessages(s?.messages ?? []);
    setApiHistory(s?.apiHistory ?? []);
    setEscalated(s?.escalated ?? false);
    setError(null);
  }, [userId, loading]);

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
    const turn = conversation.current;
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
      // Signed out (or started over) while waiting: this reply and the
      // history it carries are the previous conversation's, child data
      // included, and must not land in the new one.
      if (conversation.current !== turn) return;
      const next = [...messages, { role: "user" as const, text }, { role: "assistant" as const, text: data.reply }];
      setApiHistory(data.history);
      setEscalated(data.escalated);
      setMessages(next);
      save({ userId, messages: next, apiHistory: data.history, escalated: data.escalated });
    } catch (err) {
      if (conversation.current === turn) setError(err instanceof Error ? err.message : t("Something went wrong - please try again."));
    } finally {
      setSending(false);
    }
  }

  function clearChat() {
    conversation.current += 1;
    setMessages([]);
    setApiHistory([]);
    setEscalated(false);
    setError(null);
    try {
      sessionStorage.removeItem(STORE_KEY);
    } catch {
      // Nothing saved to remove.
    }
    trackEvent("chat_cleared");
  }

  async function copyReply(i: number, text: string) {
    try {
      await navigator.clipboard.writeText(toPlainText(text));
      setCopied(i);
      setTimeout(() => setCopied((c) => (c === i ? null : c)), 2000);
      trackEvent("chat_reply_copied");
    } catch {
      // No clipboard access (old browser, insecure context) - the text is still selectable.
    }
  }

  function shareReply(text: string) {
    trackEvent("chat_reply_shared");
    navigator.share({ text: toPlainText(text), url: window.location.origin }).catch(() => undefined);
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
                {m.role === "assistant" ? (
                  <>
                    <ChatText text={m.text} />
                    <div className="chat-actions">
                      <button type="button" className="chat-action" onClick={() => copyReply(i, m.text)}>
                        {copied === i ? <IconCheck /> : <IconCopy />}
                        {copied === i ? t("Copied") : t("Copy")}
                      </button>
                      {canShare && (
                        <button type="button" className="chat-action" onClick={() => shareReply(m.text)}>
                          <IconShare />
                          {t("Share")}
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  m.text
                )}
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
          {messages.length > 0 && !sending && (
            <div className="chat-toolbar">
              <button type="button" className="chat-action" onClick={clearChat}>
                <IconRefresh />
                {t("New chat")}
              </button>
            </div>
          )}
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
