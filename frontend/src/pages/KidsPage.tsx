import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// /kids used to list a guardian's children; My family (/family) does that now,
// with what each one has switched on. A student's own login has exactly one
// student - itself - so it still lands on its own view.
export function KidsPage() {
  const { user } = useAuth();
  const own = user?.student_profile_id;
  return <Navigate to={own ? `/kids/${own}` : "/family"} replace />;
}
