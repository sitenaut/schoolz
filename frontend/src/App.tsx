import { BrowserRouter, Route, Navigate, useLocation } from "react-router-dom";
import { FaroRoutes } from "./lib/telemetry";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { ROUTER_BASENAME } from "./lib/i18n";
import { MySchoolsProvider } from "./lib/mySchools";
import { ThemeProvider } from "./lib/theme";
import { TodayPage } from "./pages/TodayPage";
import { PickSchoolsPage } from "./pages/PickSchoolsPage";
import { LunchPage } from "./pages/LunchPage";
import { LocalPage } from "./pages/LocalPage";
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
import { SchoolClassYearPage } from "./pages/schools/SchoolClassYearPage";
import { CalendarPage } from "./pages/CalendarPage";
import { JobsPage } from "./pages/JobsPage";
import { AdminConfigPage } from "./pages/AdminConfigPage";
import { ChatbotAdminPage } from "./pages/ChatbotAdminPage";
import { AdminIndexRedirect, AdminLayout } from "./pages/AdminLayout";
import { UsersRolesPage } from "./pages/UsersRolesPage";
import { ApiKeysPage } from "./pages/ApiKeysPage";
import { ApproveApiKeyPage } from "./pages/ApproveApiKeyPage";
import { can, isStaff } from "./lib/permissions";
import { PrivacyPage } from "./pages/PrivacyPage";
import { BackpackCapturePrivacyPage } from "./pages/BackpackCapturePrivacyPage";
import { ContactPage } from "./pages/ContactPage";
import { ChCommsPage } from "./pages/ChCommsPage";
import { SurveyPage } from "./pages/SurveyPage";
import { SubmissionsPage } from "./pages/SubmissionsPage";
import { SubmissionReviewPage } from "./pages/SubmissionReviewPage";
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
// scheduled scans, Gmail scanners). `permission` names the role grant the
// page needs; `superOnly` restricts it to super admins; with neither, any
// admin (super or scoped) may enter. Anyone else - a plain guardian, or a
// scoped admin lacking the grant - gets bounced to the public home, not the
// login page (they're already logged in).
function RequireAdmin({
  children,
  permission,
  superOnly,
}: {
  children: React.ReactElement;
  permission?: string;
  superOnly?: boolean;
}) {
  const { user, loading, authTimedOut } = useAuth();
  const location = useLocation();
  if (loading) return <AuthGateFallback timedOut={authTimedOut} />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  const allowed = superOnly ? user.is_admin : permission ? can(user, permission) : isStaff(user);
  if (!allowed) return <Navigate to="/" replace />;
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
              <RequireAdmin permission="analytics.view">
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
            <RequireAdmin permission="email.view">
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
        {/* react-router v6 can't match a literal prefix inside a dynamic
            segment ("class-of-:gradYear") - a segment is either fully
            static or fully dynamic. Routed on the whole segment instead
            and parsed client-side, to keep the URL shape
            /schools/{slug}/class-of-{year} intact. */}
        <Route path="/schools/:schoolId/:classSlug" element={<SchoolClassYearPage />} />
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
            <RequireAdmin permission="submissions.view">
              <SubmissionsPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/admin/submissions/:submissionId"
          element={
            <RequireAdmin permission="submissions.view">
              <SubmissionReviewPage />
            </RequireAdmin>
          }
        />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/local" element={<LocalPage />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <AdminLayout />
            </RequireAdmin>
          }
        >
          <Route index element={<AdminIndexRedirect />} />
          <Route path="inbox" element={<RequireAdmin permission="inbox.view"><InboxPage /></RequireAdmin>} />
          <Route path="newsletters" element={<RequireAdmin permission="newsletters.manage"><SmoreNewslettersPage /></RequireAdmin>} />
          <Route path="scans" element={<RequireAdmin permission="scans.view"><JobsPage /></RequireAdmin>} />
          <Route path="chatbot" element={<RequireAdmin permission="chatbot.view"><ChatbotAdminPage /></RequireAdmin>} />
          <Route path="config" element={<RequireAdmin permission="config.view"><AdminConfigPage /></RequireAdmin>} />
          <Route path="kids" element={<RequireAdmin permission="kids.view"><KidsPage /></RequireAdmin>} />
          <Route path="users" element={<RequireAdmin superOnly><UsersRolesPage /></RequireAdmin>} />
          <Route path="api-keys" element={<RequireAdmin superOnly><ApiKeysPage /></RequireAdmin>} />
          <Route path="api-keys/approve" element={<RequireAdmin superOnly><ApproveApiKeyPage /></RequireAdmin>} />
        </Route>
      </Route>
    </FaroRoutes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME}>
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
