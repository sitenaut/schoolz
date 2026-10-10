import { useEffect, useRef } from "react";
import { TURNSTILE_SITE_KEY } from "../authConfig";

type Turnstile = {
  render: (el: HTMLElement, options: Record<string, unknown>) => string;
  reset: (id: string) => void;
  remove: (id: string) => void;
};

declare global {
  interface Window {
    turnstile?: Turnstile;
  }
}

export const BOT_CHECK_ENABLED = Boolean(TURNSTILE_SITE_KEY);

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let loading: Promise<Turnstile> | null = null;

// Loaded only by the page that renders the widget, never from index.html:
// no other page should pay for (or be tracked by) a third-party script.
function loadTurnstile(): Promise<Turnstile> {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  loading ??= new Promise<Turnstile>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error("turnstile missing")));
    script.onerror = () => {
      loading = null;
      reject(new Error("turnstile failed to load"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

type Props = {
  /** The one-time token to send with the form, or null while there isn't a valid one. */
  onToken: (token: string | null) => void;
  /** Called when the check can't run at all (script blocked, widget error). */
  onUnavailable?: () => void;
  /** Bump to get a fresh challenge - a token is spent by one submit, successful or not. */
  resetKey?: number;
};

/** The "are you a person" check (Cloudflare Turnstile). Usually resolves on
 * its own with no puzzle. Renders nothing when no site key is configured. */
export function BotCheck({ onToken, onUnavailable, resetKey = 0 }: Props) {
  const box = useRef<HTMLDivElement | null>(null);
  const widget = useRef<string | null>(null);
  const handlers = useRef({ onToken, onUnavailable });
  handlers.current = { onToken, onUnavailable };

  useEffect(() => {
    if (!BOT_CHECK_ENABLED) return;
    let cancelled = false;
    loadTurnstile()
      .then((turnstile) => {
        if (cancelled || !box.current) return;
        widget.current = turnstile.render(box.current, {
          sitekey: TURNSTILE_SITE_KEY,
          action: "upload",
          callback: (token: string) => handlers.current.onToken(token),
          "expired-callback": () => handlers.current.onToken(null),
          "error-callback": () => {
            handlers.current.onToken(null);
            handlers.current.onUnavailable?.();
          },
        });
      })
      .catch(() => handlers.current.onUnavailable?.());
    return () => {
      cancelled = true;
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current);
      widget.current = null;
    };
  }, []);

  useEffect(() => {
    if (resetKey > 0 && widget.current && window.turnstile) {
      handlers.current.onToken(null);
      window.turnstile.reset(widget.current);
    }
  }, [resetKey]);

  if (!BOT_CHECK_ENABLED) return null;
  return <div ref={box} className="bot-check" />;
}
