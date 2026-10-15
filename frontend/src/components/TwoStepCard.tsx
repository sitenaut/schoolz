import { useEffect, useState } from "react";
import { IconShield } from "./icons";
import { Badge } from "./ui/Badge";
import { Field } from "./ui/Field";
import { SectionCard } from "./ui/SectionCard";
import { useToast } from "./ui/Toast";
import { useAuth } from "../context/AuthContext";
import { removeFactor, startEnrollment, verifiedTotpFactorId, verifyCode, type Enrollment } from "../lib/mfa";

/** Account → Security: turn two-step sign-in (an authenticator app) on or
 * off. Shown to anyone with admin access; see lib/mfa.ts. */
export function TwoStepCard() {
  const { refresh } = useAuth();
  const toast = useToast();
  const [factorId, setFactorId] = useState<string | null | undefined>(undefined);
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    verifiedTotpFactorId()
      .then(setFactorId)
      .catch((e: Error) => {
        setFactorId(null);
        setError(e.message);
      });
  }, []);

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const start = () => run(async () => setEnrollment(await startEnrollment()));

  const finish = (e: React.FormEvent) => {
    e.preventDefault();
    if (!enrollment) return;
    void run(async () => {
      await verifyCode(enrollment.factorId, code);
      setFactorId(enrollment.factorId);
      setEnrollment(null);
      setCode("");
      await refresh();
      toast({ title: "Two-step sign-in is on", tone: "ok" });
    });
  };

  const turnOff = () =>
    run(async () => {
      if (!factorId) return;
      await removeFactor(factorId);
      setFactorId(null);
      await refresh();
      toast({ title: "Two-step sign-in is off", tone: "ok" });
    });

  return (
    <SectionCard
      title="Two-step sign-in"
      description="Admin pages ask for a 6-digit code from an authenticator app, so a stolen password alone can't open them."
      icon={<IconShield />}
      actions={factorId ? <Badge tone="ok">On</Badge> : factorId === null ? <Badge tone="warn">Off</Badge> : null}
    >
      {error && <div className="form-error">{error}</div>}
      {factorId === undefined && !error && <p className="muted">Checking…</p>}
      {factorId && (
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <p style={{ margin: 0, flex: 1 }}>Your authenticator app is set up. Each new sign-in to admin pages asks for its code.</p>
          <button className="btn sm" onClick={turnOff} disabled={busy}>
            Turn off
          </button>
        </div>
      )}
      {factorId === null && !enrollment && (
        <button className="btn btn-primary" onClick={start} disabled={busy}>
          Set up an authenticator app
        </button>
      )}
      {enrollment && (
        <form onSubmit={finish}>
          <ol style={{ paddingLeft: 18 }}>
            <li>Open an authenticator app (1Password, Google Authenticator, Authy…) and scan this code.</li>
            <li>Type the 6-digit code it shows.</li>
          </ol>
          <img src={enrollment.qrCode} alt="QR code for your authenticator app" width={180} height={180} />
          <p className="muted" style={{ fontSize: 12, wordBreak: "break-all" }}>
            Can't scan? Enter this key instead: <code>{enrollment.secret}</code>
          </p>
          <Field label="6-digit code">
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9 ]{6,7}"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
          </Field>
          <button className="btn btn-primary" type="submit" disabled={busy || code.replace(/\s+/g, "").length !== 6}>
            Turn on
          </button>
        </form>
      )}
    </SectionCard>
  );
}
