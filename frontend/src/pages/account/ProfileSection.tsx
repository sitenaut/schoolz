import { useEffect, useState } from "react";
import { APP_VERSION } from "../../authConfig";
import { IconMail, IconUser } from "../../components/icons";
import { Badge } from "../../components/ui/Badge";
import { Field } from "../../components/ui/Field";
import { SectionCard } from "../../components/ui/SectionCard";
import { useToast } from "../../components/ui/Toast";
import { useAuth } from "../../context/AuthContext";
import { updateProfile } from "../../lib/account";

function initials(name: string): string {
  const parts = name.replace(/[._-]+/g, " ").trim().split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2)).toUpperCase();
}

export function ProfileSection() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [username, setUsername] = useState(user?.username ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setUsername(user?.username ?? ""), [user?.username]);
  if (!user) return null;

  const dirty = username.trim() !== user.username;
  const method = user.sign_in_method === "google" ? "Google" : user.auth_mode === "supabase" ? "Email & password" : "Local password";
  const since = user.created_at ? new Date(user.created_at).toLocaleDateString(undefined, { month: "long", year: "numeric" }) : null;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await updateProfile(username.trim());
      await refresh();
      toast({ title: "Profile saved", tone: "ok" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SectionCard
        title="Profile"
        description="How you appear on schoolz - other guardians see your username on shared children."
        icon={<IconUser />}
        footer={
          <>
            <button className="btn" type="button" onClick={() => setUsername(user.username)} disabled={!dirty || busy}>
              Cancel
            </button>
            <button className="btn btn-primary" type="submit" form="profile-form" disabled={!dirty || busy || username.trim().length < 3}>
              {busy ? "Saving…" : "Save changes"}
            </button>
          </>
        }
      >
        <div className="profile-hd">
          <div className="avatar-lg" aria-hidden="true">
            {initials(user.username)}
          </div>
          <div style={{ minWidth: 0 }}>
            <h3>{user.username}</h3>
            <div className="meta">
              <span>{user.email}</span>
              <Badge tone="info" dot={false}>
                {method}
              </Badge>
              {user.is_admin && (
                <Badge tone="warn" dot={false}>
                  Admin
                </Badge>
              )}
            </div>
          </div>
        </div>

        <form id="profile-form" onSubmit={save}>
          {error && <div className="form-error">{error}</div>}
          <div className="fgrid two">
            <Field label="Username" hint="3-64 characters. Shown to guardians you share a child with.">
              <input value={username} onChange={(e) => setUsername(e.target.value)} minLength={3} maxLength={64} required />
            </Field>
            <Field label="Email" hint={user.auth_mode === "supabase" ? "Managed by your sign-in provider." : "Used to sign in and for password resets."}>
              <input value={user.email} readOnly />
            </Field>
          </div>
        </form>
      </SectionCard>

      <SectionCard title="Account" description="Where this account comes from." icon={<IconMail />}>
        <div className="info-row">
          <span className="ico">
            <IconMail />
          </span>
          <div className="txt">
            <b>{user.email}</b>
            <small>Primary email · signs in with {method}</small>
          </div>
          <Badge tone="ok" dot={false}>
            Verified
          </Badge>
        </div>
        <div className="kv" style={{ marginTop: 10 }}>
          <dt>Member since</dt>
          <dd>{since ?? "—"}</dd>
          <dt>Auth mode</dt>
          <dd>{user.auth_mode}</dd>
          <dt>Build</dt>
          <dd>
            <span className="code-chip">{APP_VERSION}</span>
          </dd>
        </div>
      </SectionCard>
    </>
  );
}
