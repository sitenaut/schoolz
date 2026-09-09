import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AuthPanel } from "../components/AuthPanel";
import { useAuth } from "../context/AuthContext";

/** Full-page version, reached the same way LoginPage is - see its note. */
export function RegisterPage() {
  const { user } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("register");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = searchParams.get("next") || "/";

  useEffect(() => {
    if (user) navigate(next, { replace: true });
  }, [user, navigate, next]);

  return (
    <div className="page page-narrow">
      <h1>{mode === "login" ? "Sign in" : "Register"}</h1>
      <AuthPanel mode={mode} onModeChange={setMode} />
    </div>
  );
}
