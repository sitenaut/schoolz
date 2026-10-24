import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";

type ConnectRequest = {
  user_code: string;
  client_name: string;
  created_at: string;
  expires_at: string;
  status: "pending" | "approved" | "denied" | "issued" | "expired";
  // From this same internet connection. When not, Connect needs the code
  // typed in from the popup on that computer.
  same_network: boolean;
};

/** Where Backpack Capture's "Connect to schoolz" lands (it opens this tab
 * itself): one button that gives that computer's extension a key to this
 * account - whatever way the person signs in here, nothing typed into the
 * extension. The extension collects the key and closes the tab on its own.
 * The code has to match the one the extension shows: a link someone else
 * sent would carry their code, not the one on this person's screen. So when
 * the request came from another connection, the page doesn't show the code
 * at all and asks for it to be typed in from the popup - a parent sent a
 * stranger's link has no popup showing it. */
export function ConnectBackpackPage() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const [params] = useSearchParams();
  const code = (params.get("code") ?? "").trim();
  const [req, setReq] = useState<ConnectRequest | null>(null);
  const [missing, setMissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  const load = useCallback(
    () =>
      apiFetch(`/capture-devices/requests/${encodeURIComponent(code)}`).then(async (r) => {
        if (r.status === 404) setMissing(true);
        else if (r.ok) setReq(await r.json());
      }),
    [code],
  );

  useEffect(() => {
    if (!user || !code) return;
    let alive = true;
    apiFetch(`/capture-devices/requests/${encodeURIComponent(code)}`).then(async (r) => {
      if (!alive) return;
      if (r.status === 404) setMissing(true);
      else if (r.ok) setReq(await r.json());
    });
    return () => {
      alive = false;
    };
  }, [user, code]);

  // After Connect, watch for the extension to collect its key.
  useEffect(() => {
    if (req?.status !== "approved") return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [req?.status, load]);

  if (loading) return <p className="note" style={{ margin: "3rem" }}>Loading…</p>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;

  const answer = async (action: "approve" | "deny") => {
    setBusy(true);
    setError(null);
    try {
      const typedCode = action === "approve" && req && !req.same_network ? { typed_code: typed } : null;
      const r = await apiFetch(`/capture-devices/requests/${encodeURIComponent(code)}/${action}`, {
        method: "POST",
        ...(typedCode ? { body: JSON.stringify(typedCode) } : {}),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Something went wrong");
      }
      setReq(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const outcome: Record<Exclude<ConnectRequest["status"], "pending">, string> = {
    approved: "Connecting… Backpack Capture finishes on its own in a moment.",
    issued: "Connected. Go back to Backpack Capture and press Update now. You can close this tab.",
    denied: "Cancelled. That computer wasn't connected.",
    expired: "This request expired. Press Connect to schoolz in Backpack Capture again.",
  };

  return (
    <div className="page">
      <div className="eyebrow">Backpack Capture</div>
      <h1>Connect this computer</h1>
      {!code || missing ? (
        <div className="empty">This link has no valid code. Press Connect to schoolz in Backpack Capture again.</div>
      ) : !req ? (
        <p className="note">Loading…</p>
      ) : (
        <div className="card">
          <p style={{ marginTop: 0 }}>
            Backpack Capture on <strong>{req.client_name.replace(/^Backpack Capture on /, "") || "a computer"}</strong> wants
            to send your children's Google Classroom work to your schoolz account, <strong>{user.email}</strong>.
          </p>
          {req.same_network ? (
            <div style={{ textAlign: "center", margin: "16px 0" }}>
              <div className="note">Code</div>
              <div style={{ fontFamily: "var(--mono, monospace)", fontSize: 30, fontWeight: 700, letterSpacing: "0.12em" }}>
                {req.user_code}
              </div>
            </div>
          ) : (
            req.status === "pending" && (
              <div style={{ margin: "16px 0" }}>
                <p>
                  This request came from a different internet connection than the one you're on now. Type the code that
                  Backpack Capture's popup shows on that computer.
                </p>
                <input
                  aria-label="Code from Backpack Capture"
                  placeholder="ABCD-EFGH"
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  maxLength={20}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  style={{ fontFamily: "var(--mono, monospace)", fontSize: 22, letterSpacing: "0.12em", maxWidth: 260 }}
                />
              </div>
            )
          )}
          {req.status === "pending" ? (
            <>
              <p className="note">
                Only connect if you just pressed Connect to schoolz in Backpack Capture yourself (its popup shows this same
                code). If someone sent you this link, press Cancel. It can send pages and see your children's names, nothing
                else. You can disconnect it any time under <Link to="/account/security">Account → Security</Link>.
              </p>
              {error && <div className="banner bad">{error}</div>}
              <div className="actions bare" style={{ marginTop: 12 }}>
                <button
                  className="action primary"
                  disabled={busy || (!req.same_network && typed.replace(/[^a-z0-9]/gi, "").length !== 8)}
                  onClick={() => answer("approve")}
                >
                  {busy ? "Connecting…" : "Connect"}
                </button>
                <button className="action" disabled={busy} onClick={() => answer("deny")}>
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <p style={{ marginBottom: 0 }}>{outcome[req.status]}</p>
          )}
        </div>
      )}
    </div>
  );
}
