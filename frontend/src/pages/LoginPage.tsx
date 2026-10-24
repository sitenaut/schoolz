import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AuthPanel } from "../components/AuthPanel";
import { useAuth } from "../context/AuthContext";
import { goToNext, returnToFor, safeNext } from "../lib/safeNext";

/** The full-page version - only reached via a direct link (an invite's
 * `?next=` redirect, a bookmark, or landing here with JS routing not yet
 * ready). The normal path is the top-right popover in AppShell. */
export function LoginPage() {
  const { user } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const presetEmail = searchParams.get("email") ?? undefined;

  useEffect(() => {
    if (user) goToNext(next, navigate);
  }, [user, navigate, next]);

  return (
    <div className="page page-narrow">
      <h1>{mode === "login" ? "Sign in" : "Register"}</h1>
      <AuthPanel
        mode={mode}
        onModeChange={setMode}
        returnTo={returnToFor(next)}
        presetEmail={presetEmail}
      />
    </div>
  );
}
