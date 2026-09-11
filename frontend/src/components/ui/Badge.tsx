import type { ReactNode } from "react";

export type Tone = "ok" | "warn" | "bad" | "info" | "muted";

export function Badge({ tone = "muted", dot = true, className = "", children }: { tone?: Tone; dot?: boolean; className?: string; children: ReactNode }) {
  return <span className={`badge ${tone} ${dot ? "" : "nodot"} ${className}`}>{children}</span>;
}

const STATUS: Record<string, { tone: Tone; label: string; extra?: string }> = {
  success: { tone: "ok", label: "Success" },
  warning: { tone: "warn", label: "Warning" },
  error: { tone: "bad", label: "Failed" },
  running: { tone: "info", label: "Running", extra: "running" },
  skipped: { tone: "muted", label: "Skipped" },
};

/** JobRun.status / ScheduledJob.last_status → colored pill. Null = never run. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge tone="muted">Never run</Badge>;
  const s = STATUS[status] ?? { tone: "muted" as Tone, label: status };
  return (
    <Badge tone={s.tone} className={s.extra ?? ""}>
      {s.label}
    </Badge>
  );
}
