import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

type Tone = "ok" | "bad" | "warn" | "info";
type ToastInput = { title: string; description?: string; tone?: Tone; duration?: number };
type ToastItem = ToastInput & { id: number };

const ToastContext = createContext<{ toast: (t: ToastInput) => void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => setItems((cur) => cur.filter((t) => t.id !== id)), []);
  const toast = useCallback(
    (t: ToastInput) => {
      const id = ++seq.current;
      setItems((cur) => [...cur.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.duration ?? (t.tone === "bad" ? 7000 : 4000));
    },
    [dismiss]
  );
  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {items.length > 0 && (
        <div className="toasts" role="status" aria-live="polite">
          {items.map((t) => (
            <div className={`toast ${t.tone ?? "info"}`} key={t.id}>
              <div style={{ minWidth: 0 }}>
                <b>{t.title}</b>
                {t.description && <small>{t.description}</small>}
              </div>
              <button onClick={() => dismiss(t.id)} aria-label="Dismiss">
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx.toast;
}
