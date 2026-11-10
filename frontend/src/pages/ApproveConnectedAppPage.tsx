import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";

type ConnectRequest = {
  user_code: string;
  client_name: string;
  created_at: string;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "issued" | "expired";
};

/** Where an app's "Connect to schoolz" sends you (billz shows this link and
 * its code): approve it from any signed-in browser, usually a phone. The key
 * goes straight to the app; nothing here ever shows it. */
export function ApproveConnectedAppPage() {
  const [params] = useSearchParams();
  const code = (params.get("code") ?? "").trim();
  const [req, setReq] = useState<ConnectRequest | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!code) return;
    const r = await apiFetch(`/admin/family-connections/requests/${encodeURIComponent(code)}`);
    if (r.status === 404) setMissing(true);
    else if (r.ok) setReq(await r.json());
  }, [code]);

  useEffect(() => {
    if (!code) return;
    let alive = true;
    apiFetch(`/admin/family-connections/requests/${encodeURIComponent(code)}`).then(async (r) => {
      if (!alive) return;
      if (r.status === 404) setMissing(true);
      else if (r.ok) setReq(await r.json());
    });
    return () => {
      alive = false;
    };
  }, [code]);

  // After approving, watch for the app to collect its key.
  useEffect(() => {
    if (req?.status !== "approved") return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [req?.status, load]);

  const answer = async (action: "approve" | "deny") => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/admin/family-connections/requests/${encodeURIComponent(code)}/${action}`, { method: "POST" });
      if (!r.ok) {
        const detail = await r.json().catch(() => null);
        throw new Error(typeof detail?.detail === "string" ? detail.detail : "Something went wrong");
      }
      setReq(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const header = <PageHeader title="Connect an app" back={{ to: "/admin/connected-apps", label: "Connected apps" }} />;

  if (!code || missing) {
    return (
      <div>
        {header}
        <SectionCard title="No such request">
          <p className="note">This link has no valid code. Start the connection again from the app.</p>
        </SectionCard>
      </div>
    );
  }
  if (!req) return <div>{header}</div>;

  const done: Record<Exclude<ConnectRequest["status"], "pending">, string> = {
    approved: `Approved. Waiting for ${req.client_name} to collect its key…`,
    issued: `Connected. ${req.client_name} has its key. You can close this page.`,
    denied: `Cancelled. ${req.client_name} got nothing.`,
    expired: "This request expired. Start the connection again from the app.",
  };

  return (
    <div>
      {header}
      <SectionCard
        title="Connect request"
        description="Only approve if you just started this in the app yourself, in the last few minutes."
      >
        <div style={{ textAlign: "center", margin: "4px 0 12px" }}>
          <div className="note">Code</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: 30, fontWeight: 700, letterSpacing: "0.12em" }}>{req.user_code}</div>
          <div className="note">It must match the code {req.client_name} shows.</div>
        </div>
        <p style={{ margin: 0 }}>
          <strong>{req.client_name}</strong> wants to read your children's first names, their schools, school days and
          schedules, school events and newsletter items, schoolwork and grades. It can't see anything else or change
          anything.
        </p>
      </SectionCard>

      {req.status !== "pending" ? (
        <SectionCard title={req.status === "issued" ? "Connected" : "Status"}>
          <p style={{ margin: 0 }}>{done[req.status]}</p>
          {req.status === "issued" && (
            <p className="note">
              It's listed under <Link to="/admin/connected-apps">Connected apps</Link>, where you can disconnect it.
            </p>
          )}
        </SectionCard>
      ) : (
        <SectionCard title="Your answer">
          {error && <div className="form-error">{error}</div>}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
            <button className="btn" disabled={busy} onClick={() => answer("deny")}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={busy} onClick={() => answer("approve")}>
              {busy ? "Working…" : "Connect"}
            </button>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
