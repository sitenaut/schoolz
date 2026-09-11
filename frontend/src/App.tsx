import { BrowserRouter, Route, Navigate } from "react-router-dom";
import { FaroRoutes } from "./lib/telemetry";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AccountPage } from "./pages/AccountPage";
import { AppShell } from "./components/AppShell";
import { MySchoolsProvider } from "./lib/mySchools";
import { ThemeProvider } from "./lib/theme";
import { TodayPage } from "./pages/TodayPage";
import { PickSchoolsPage } from "./pages/PickSchoolsPage";
import { LunchPage } from "./pages/LunchPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ChildrenPage } from "./pages/ChildrenPage";
import { InviteAcceptPage } from "./pages/InviteAcceptPage";
import { GmailPage } from "./pages/GmailPage";
import { SmoreNewslettersPage } from "./pages/SmoreNewslettersPage";
import { SchoolsPage } from "./pages/SchoolsPage";
import { SchoolDetailPage } from "./pages/SchoolDetailPage";
import { CalendarPage } from "./pages/CalendarPage";
import { JobsPage } from "./pages/JobsPage";
import { AdminConfigPage } from "./pages/AdminConfigPage";
import { PrivacyPage } from "./pages/PrivacyPage";

// Gates the *optional* personal layer (my kids, my calendar, connecting
// Gmail) - never the public directory/calendar/school pages, which are
// meant to be browsed and bookmarked without an account at all.
function RequireAuth({ children }: { children: React.ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) return <p>Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

// Gates the centrally-managed admin tooling (districts, Smore links,
// scheduled scans) - a logged-in guardian without is_admin gets bounced
// to the public home, not the login page (they're already logged in).
function RequireAdmin({ children }: { children: React.ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) return <p>Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/" replace />;
  return children;
}

function Routed() {
  return (
    <FaroRoutes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<AppShell />}>
      <Route path="/" element={<TodayPage />} />
      <Route path="/start" element={<PickSchoolsPage />} />
      <Route path="/lunch" element={<LunchPage />} />
      <Route
        path="/account"
        element={
          <RequireAuth>
            <AccountPage />
          </RequireAuth>
        }
      />
      <Route
        path="/children"
        element={
          <RequireAuth>
            <ChildrenPage />
          </RequireAuth>
        }
      />
      <Route path="/invites/:token" element={<InviteAcceptPage />} />
      <Route
        path="/gmail"
        element={
          <RequireAuth>
            <GmailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/smore"
        element={
          <RequireAdmin>
            <SmoreNewslettersPage />
          </RequireAdmin>
        }
      />
      <Route path="/schools" element={<SchoolsPage />} />
      <Route path="/schools/:schoolId" element={<SchoolDetailPage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/calendar" element={<CalendarPage />} />
      <Route
        path="/jobs"
        element={
          <RequireAdmin>
            <JobsPage />
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/config"
        element={
          <RequireAdmin>
            <AdminConfigPage />
          </RequireAdmin>
        }
      />
      </Route>
    </FaroRoutes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <MySchoolsProvider>
            <Routed />
          </MySchoolsProvider>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
