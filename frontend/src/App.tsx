import { BrowserRouter, Route, Navigate } from "react-router-dom";
import { FaroRoutes } from "./lib/telemetry";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { MySchoolsProvider } from "./lib/mySchools";
import { ThemeProvider } from "./lib/theme";
import { TodayPage } from "./pages/TodayPage";
import { PickSchoolsPage } from "./pages/PickSchoolsPage";
import { LunchPage } from "./pages/LunchPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { ChildrenPage } from "./pages/ChildrenPage";
import { KidsPage } from "./pages/KidsPage";
import { KidsDetailPage } from "./pages/KidsDetailPage";
import { InvitePage } from "./pages/InvitePage";
import { GmailPage } from "./pages/GmailPage";
import { SmoreNewslettersPage } from "./pages/SmoreNewslettersPage";
import { SchoolsPage } from "./pages/SchoolsPage";
import { DirectoryPage } from "./pages/DirectoryPage";
import { SchoolDetailPage } from "./pages/SchoolDetailPage";
import { CalendarPage } from "./pages/CalendarPage";
import { JobsPage } from "./pages/JobsPage";
import { AdminConfigPage } from "./pages/AdminConfigPage";
import { AdminLayout } from "./pages/AdminLayout";
import { PrivacyPage } from "./pages/PrivacyPage";
import { BackpackCapturePrivacyPage } from "./pages/BackpackCapturePrivacyPage";
import { ContactPage } from "./pages/ContactPage";
import { ChCommsPage } from "./pages/ChCommsPage";
import { SurveyPage } from "./pages/SurveyPage";
import { SubmissionsPage } from "./pages/SubmissionsPage";
import { SubmitSourcePage } from "./pages/SubmitSourcePage";
import { InboxPage } from "./pages/InboxPage";
import { AccountLayout } from "./pages/account/AccountLayout";
import { ProfileSection } from "./pages/account/ProfileSection";
import { SecuritySection } from "./pages/account/SecuritySection";
import { NotificationsSection } from "./pages/account/NotificationsSection";
import { PrivacySection } from "./pages/account/PrivacySection";
import { FamilySection } from "./pages/account/FamilySection";
import { AdminSection } from "./pages/account/AdminSection";

// Gates the *optional* personal layer (my kids, my calendar, account
// settings) - never the public directory/calendar/school pages, which are
// meant to be browsed and bookmarked without an account at all.
// A stalled auth check used to render "Loading…" indefinitely, leaving a
// hand-reload as the visitor's only way out (see the onAuthStateChange
// comment in AuthContext for what stalled it). Offer that reload
// explicitly rather than hanging silently - and never redirect on a
// timeout, since a stuck check says nothing about whether they're signed
// in, and bouncing a signed-in visitor to /login would be worse.
function AuthGateFallback({ timedOut }: { timedOut: boolean }) {
  if (!timedOut) return <p>Loading…</p>;
  return (
    <div style={{ padding: "2rem", textAlign: "center" }}>
      <p>This is taking longer than usual.</p>
      <button className="btn" onClick={() => window.location.reload()}>
        Reload
      </button>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactElement }) {
  const { user, loading, authTimedOut } = useAuth();
  if (loading) return <AuthGateFallback timedOut={authTimedOut} />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

// Gates the centrally-managed admin tooling (districts, Smore links,
// scheduled scans, Gmail scanners) - a logged-in guardian without is_admin gets bounced
// to the public home, not the login page (they're already logged in).
function RequireAdmin({ children }: { children: React.ReactElement }) {
  const { user, loading, authTimedOut } = useAuth();
  if (loading) return <AuthGateFallback timedOut={authTimedOut} />;
  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/" replace />;
  return children;
}

function Routed() {
  return (
    <FaroRoutes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<AppShell />}>
        <Route path="/" element={<TodayPage />} />
        <Route path="/start" element={<PickSchoolsPage />} />
        <Route path="/lunch" element={<LunchPage />} />
        <Route
          path="/account"
          element={
            <RequireAuth>
              <AccountLayout />
            </RequireAuth>
          }
        >
          <Route index element={<ProfileSection />} />
          <Route path="security" element={<SecuritySection />} />
          <Route path="privacy" element={<PrivacySection />} />
          <Route path="notifications" element={<NotificationsSection />} />
          <Route path="family" element={<FamilySection />} />
          <Route
            path="admin"
            element={
              <RequireAdmin>
                <AdminSection />
              </RequireAdmin>
            }
          />
        </Route>
        <Route
          path="/children"
          element={
            <RequireAuth>
              <ChildrenPage />
            </RequireAuth>
          }
        />
        <Route path="/invites/:token" element={<InvitePage kind="guardian" />} />
        <Route path="/student-invites/:token" element={<InvitePage kind="student" />} />
        <Route
          path="/kids"
          element={
            <RequireAuth>
              <KidsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/kids/:studentId"
          element={
            <RequireAuth>
              <KidsDetailPage />
            </RequireAuth>
          }
        />
        <Route
          path="/gmail"
          element={
            <RequireAdmin>
              <GmailPage />
            </RequireAdmin>
          }
        />
        {/* Old bookmarked/linked paths - keep working, just land on the
            consolidated tab now. */}
        <Route path="/smore" element={<Navigate to="/admin/newsletters" replace />} />
        <Route path="/jobs" element={<Navigate to="/admin/scans" replace />} />
        <Route path="/schools" element={<SchoolsPage />} />
        <Route path="/schools/:schoolId" element={<SchoolDetailPage />} />
        <Route path="/directory" element={<DirectoryPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/backpack-capture/privacy" element={<BackpackCapturePrivacyPage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/contact/submit" element={<SubmitSourcePage />} />
        <Route path="/chcomms" element={<ChCommsPage />} />
        <Route path="/survey" element={<SurveyPage />} />
        <Route
          path="/admin/submissions"
          element={
            <RequireAdmin>
              <SubmissionsPage />
            </RequireAdmin>
          }
        />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <AdminLayout />
            </RequireAdmin>
          }
        >
          <Route index element={<Navigate to="/admin/newsletters" replace />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="newsletters" element={<SmoreNewslettersPage />} />
          <Route path="scans" element={<JobsPage />} />
          <Route path="config" element={<AdminConfigPage />} />
          <Route path="kids" element={<KidsPage />} />
        </Route>
      </Route>
    </FaroRoutes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <ToastProvider>
          <AuthProvider>
            <MySchoolsProvider>
              <Routed />
            </MySchoolsProvider>
          </AuthProvider>
        </ToastProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
