/** Opens the chat panel from anywhere on the site with a question already
 * typed in, for the visitor to edit or send - never sent for them, since a
 * reply is a paid model call. ChatWidget is mounted once in AppShell and
 * listens; a window event keeps pages from importing it. */

const EVENT = "schoolz:open-chat";

export type ChatRequest = { draft: string; from: string };

export function openChat(draft: string, from: string): void {
  window.dispatchEvent(new CustomEvent<ChatRequest>(EVENT, { detail: { draft, from } }));
}

/** Returns the unsubscribe. */
export function onOpenChat(handler: (request: ChatRequest) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<ChatRequest>).detail);
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
