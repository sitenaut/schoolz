import { useEffect } from "react";
import { BrowserRouter, Route, Navigate, useLocation } from "react-router-dom";
import { FaroRoutes } from "./lib/telemetry";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppShell } from "./components/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { ROUTER_BASENAME } from "./lib/i18n";
import { lazyPage, preloadWhenIdle } from "./lib/lazyPage";
import { MySchoolsProvider } from "./lib/mySchools";
import { IS_PRERENDER } from "./lib/prerenderReady";
import { ThemeProvider } from "./lib/theme";
import { can, isStaff } from "./lib/permissions";
import { MfaGate } from "./components/MfaGate";
// In the main bundle: Today and a school's page are where nearly every visit
// lands (the home page, and search results), so they draw without waiting on
// a second file. The layouts are small and wrap lazy pages of their own.
import { TodayPage } from "./pages/TodayPage";
import { SchoolDetailPage } from "./pages/SchoolDetailPage";
import { LocalzLayout } from "./pages/localz/LocalzLayout";
import { AdminIndexRedirect, AdminLayout } from "./pages/AdminLayout";
import { AuditShell } from "./pages/audit/AuditShell";
import { AccountLayout } from "./pages/account/AccountLayout";

// Every other page is its own chunk, fetched when it's first opened.
const PickSchoolsPage = lazyPage(() => import("./pages/PickSchoolsPage").then((m) => m.PickSchoolsPage));
const LunchPage = lazyPage(() => import("./pages/LunchPage").then((m) => m.LunchPage));
const LocalPage = lazyPage(() => import("./pages/LocalPage").then((m) => m.LocalPage));
const LocalzHomePage = lazyPage(() => import("./pages/localz/LocalzHomePage").then((m) => m.LocalzHomePage));
const LocalzCategoryPage = lazyPage(() => import("./pages/localz/LocalzCategoryPage").then((m) => m.LocalzCategoryPage));
const LocalzResourcePage = lazyPage(() => import("./pages/localz/LocalzResourcePage").then((m) => m.LocalzResourcePage));
const ProvidersPage = lazyPage(() => import("./pages/localz/providers/ProvidersPage").then((m) => m.ProvidersPage));
const ProviderPortalPage = lazyPage(() => import("./pages/localz/providers/ProviderPortalPage").then((m) => m.ProviderPortalPage));
const ProviderRequestPage = lazyPage(() => import("./pages/localz/providers/ProviderRequestPage").then((m) => m.ProviderRequestPage));
const ProviderListingPage = lazyPage(() => import("./pages/localz/providers/ProviderListingPage").then((m) => m.ProviderListingPage));
const LocalzReviewPage = lazyPage(() => import("./pages/LocalzReviewPage").then((m) => m.LocalzReviewPage));
const LocalzReviewDetailPage = lazyPage(() => import("./pages/LocalzReviewDetailPage").then((m) => m.LocalzReviewDetailPage));
const LocalzListingAdminPage = lazyPage(() => import("./pages/LocalzListingAdminPage").then((m) => m.LocalzListingAdminPage));
const SeasonalPage = lazyPage(() => import("./pages/SeasonalPage").then((m) => m.SeasonalPage));
const LoginPage = lazyPage(() => import("./pages/LoginPage").then((m) => m.LoginPage));
const RegisterPage = lazyPage(() => import("./pages/RegisterPage").then((m) => m.RegisterPage));
const ForgotPasswordPage = lazyPage(() => import("./pages/ForgotPasswordPage").then((m) => m.ForgotPasswordPage));
const ResetPasswordPage = lazyPage(() => import("./pages/ResetPasswordPage").then((m) => m.ResetPasswordPage));
const FamilyPage = lazyPage(() => import("./pages/FamilyPage").then((m) => m.FamilyPage));
const KidsPage = lazyPage(() => import("./pages/KidsPage").then((m) => m.KidsPage));
const KidsDetailPage = lazyPage(() => import("./pages/KidsDetailPage").then((m) => m.KidsDetailPage));
const InvitePage = lazyPage(() => import("./pages/InvitePage").then((m) => m.InvitePage));
const GmailPage = lazyPage(() => import("./pages/GmailPage").then((m) => m.GmailPage));
const SmoreNewslettersPage = lazyPage(() => import("./pages/SmoreNewslettersPage").then((m) => m.SmoreNewslettersPage));
const SchoolsPage = lazyPage(() => import("./pages/SchoolsPage").then((m) => m.SchoolsPage));
const DirectoryPage = lazyPage(() => import("./pages/DirectoryPage").then((m) => m.DirectoryPage));
const SchoolClassYearPage = lazyPage(() => import("./pages/schools/SchoolClassYearPage").then((m) => m.SchoolClassYearPage));
const CalendarPage = lazyPage(() => import("./pages/CalendarPage").then((m) => m.CalendarPage));
const SchoolCalendarPage = lazyPage(() => import("./pages/CalendarPage").then((m) => m.SchoolCalendarPage));
const JobsPage = lazyPage(() => import("./pages/JobsPage").then((m) => m.JobsPage));
const AdminConfigPage = lazyPage(() => import("./pages/AdminConfigPage").then((m) => m.AdminConfigPage));
const ChatbotAdminPage = lazyPage(() => import("./pages/ChatbotAdminPage").then((m) => m.ChatbotAdminPage));
const AuditBySchoolPage = lazyPage(() => import("./pages/audit/AuditBySchoolPage").then((m) => m.AuditBySchoolPage));
const AuditCatalogPage = lazyPage(() => import("./pages/audit/AuditCatalogPage").then((m) => m.AuditCatalogPage));
const AuditReportPage = lazyPage(() => import("./pages/audit/AuditReportPage").then((m) => m.AuditReportPage));
const AuditSchoolPage = lazyPage(() => import("./pages/audit/AuditSchoolPage").then((m) => m.AuditSchoolPage));
const AdminOverviewPage = lazyPage(() => import("./pages/AdminOverviewPage").then((m) => m.AdminOverviewPage));
const UsersRolesPage = lazyPage(() => import("./pages/UsersRolesPage").then((m) => m.UsersRolesPage));
const ApiKeysPage = lazyPage(() => import("./pages/ApiKeysPage").then((m) => m.ApiKeysPage));
const ApproveApiKeyPage = lazyPage(() => import("./pages/ApproveApiKeyPage").then((m) => m.ApproveApiKeyPage));
const SecretRequestsPage = lazyPage(() => import("./pages/SecretRequestsPage").then((m) => m.SecretRequestsPage));
const AuditLogPage = lazyPage(() => import("./pages/AuditLogPage").then((m) => m.AuditLogPage));
const ApproveSecretRequestPage = lazyPage(() => import("./pages/ApproveSecretRequestPage").then((m) => m.ApproveSecretRequestPage));
const PrivacyPage = lazyPage(() => import("./pages/PrivacyPage").then((m) => m.PrivacyPage));
const BackpackCapturePrivacyPage = lazyPage(() => import("./pages/BackpackCapturePrivacyPage").then((m) => m.BackpackCapturePrivacyPage));
const ConnectBackpackPage = lazyPage(() => import("./pages/ConnectBackpackPage").then((m) => m.ConnectBackpackPage));
const ContactPage = lazyPage(() => import("./pages/ContactPage").then((m) => m.ContactPage));
const ChCommsPage = lazyPage(() => import("./pages/ChCommsPage").then((m) => m.ChCommsPage));
const SurveyPage = lazyPage(() => import("./pages/SurveyPage").then((m) => m.SurveyPage));
const SubmissionsPage = lazyPage(() => import("./pages/SubmissionsPage").then((m) => m.SubmissionsPage));
const SubmissionReviewPage = lazyPage(() => import("./pages/SubmissionReviewPage").then((m) => m.SubmissionReviewPage));
const UploadPage = lazyPage(() => import("./pages/UploadPage").then((m) => m.UploadPage));
const InboxPage = lazyPage(() => import("./pages/InboxPage").then((m) => m.InboxPage));
const SupportPage = lazyPage(() => import("./pages/SupportPage").then((m) => m.SupportPage));
const ProfileSection = lazyPage(() => import("./pages/account/ProfileSection").then((m) => m.ProfileSection));
const SecuritySection = lazyPage(() => import("./pages/account/SecuritySection").then((m) => m.SecuritySection));
const NotificationsSection = lazyPage(() => import("./pages/account/NotificationsSection").then((m) => m.NotificationsSection));
const PrivacySection = lazyPage(() => import("./pages/account/PrivacySection").then((m) => m.PrivacySection));
const SavedProfileSection = lazyPage(() => import("./pages/account/SavedProfileSection").then((m) => m.SavedProfileSection));

// The bottom tabs and the school picker Today points to, fetched once the
// landing page is done so a tap on them doesn't wait on the network.
const NEXT_TAPS = [CalendarPage, LunchPage, SchoolsPage, DirectoryPage, LocalPage, LocalzHomePage, PickSchoolsPage];

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
  return <MfaGate>{children}</MfaGate>;
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
          {/* Family moved out of settings to /family. */}
          <Route path="family" element={<Navigate to="/family" replace />} />
          <Route path="saved-answers" element={<SavedProfileSection />} />
        </Route>
        <Route
          path="/family"
          element={
            <RequireAuth>
              <FamilyPage />
            </RequireAuth>
          }
        />
        {/* My Children became My family. */}
        <Route path="/children" element={<Navigate to="/family" replace />} />
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
        {/* Old bookmarked/linked paths - keep working, just land on the
            consolidated tab now. */}
        <Route path="/account/admin" element={<Navigate to="/admin/overview" replace />} />
        <Route path="/gmail" element={<Navigate to="/admin/email" replace />} />
        <Route path="/smore" element={<Navigate to="/admin/newsletters" replace />} />
        <Route path="/jobs" element={<Navigate to="/admin/scans" replace />} />
        <Route path="/schools" element={<SchoolsPage />} />
        <Route path="/schools/:schoolId" element={<SchoolDetailPage />} />
        <Route path="/schools/:schoolId/calendar" element={<SchoolCalendarPage />} />
        {/* react-router v6 can't match a literal prefix inside a dynamic
            segment ("class-of-:gradYear") - a segment is either fully
            static or fully dynamic. Routed on the whole segment instead
            and parsed client-side, to keep the URL shape
            /schools/{slug}/class-of-{year} intact. */}
        <Route path="/schools/:schoolId/:classSlug" element={<SchoolClassYearPage />} />
        <Route path="/directory" element={<DirectoryPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/backpack-capture/privacy" element={<BackpackCapturePrivacyPage />} />
        {/* Opened by Backpack Capture's "Connect to schoolz"; signs in first if needed. */}
        <Route path="/connect" element={<ConnectBackpackPage />} />
        <Route path="/contact" element={<ContactPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/contact/submit" element={<LegacySubmitRedirect />} />
        <Route path="/chcomms" element={<ChCommsPage />} />
        <Route path="/survey" element={<SurveyPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route element={<LocalzLayout />}>
          <Route path="/local" element={<LocalPage />} />
          <Route path="/localz" element={<LocalzHomePage />} />
          <Route path="/localz/r/:resourceId" element={<LocalzResourcePage />} />
          <Route path="/localz/providers" element={<ProvidersPage />} />
          <Route path="/localz/providers/portal" element={<ProviderPortalPage />} />
          <Route path="/localz/providers/requests/:requestId" element={<ProviderRequestPage />} />
          <Route path="/localz/providers/listings/:serviceId" element={<ProviderListingPage />} />
          <Route path="/localz/:category" element={<LocalzCategoryPage />} />
        </Route>
        <Route path="/audit" element={<AuditShell pub />}>
          <Route index element={<AuditBySchoolPage />} />
          <Route path="data-points" element={<AuditCatalogPage />} />
          <Route path="report" element={<AuditReportPage />} />
          <Route path="schools/:schoolId" element={<AuditSchoolPage />} />
          <Route path="schools/:schoolId/report" element={<AuditReportPage />} />
        </Route>
        <Route path="/seasonal/:season" element={<SeasonalPage />} />
        <Route
          path="/admin"
          element={
            <RequireAdmin>
              <AdminLayout />
            </RequireAdmin>
          }
        >
          <Route index element={<AdminIndexRedirect />} />
          <Route path="overview" element={<RequireAdmin permission="analytics.view"><AdminOverviewPage /></RequireAdmin>} />
          <Route path="inbox" element={<RequireAdmin permission="inbox.view"><InboxPage /></RequireAdmin>} />
          <Route path="submissions" element={<RequireAdmin permission="submissions.view"><SubmissionsPage /></RequireAdmin>} />
          <Route path="submissions/:submissionId" element={<RequireAdmin permission="submissions.view"><SubmissionReviewPage /></RequireAdmin>} />
          <Route path="newsletters" element={<RequireAdmin permission="newsletters.manage"><SmoreNewslettersPage /></RequireAdmin>} />
          <Route path="scans" element={<RequireAdmin permission="scans.view"><JobsPage /></RequireAdmin>} />
          <Route path="audit" element={<RequireAdmin permission="audit.view"><AuditShell /></RequireAdmin>}>
            <Route index element={<AuditBySchoolPage />} />
            <Route path="data-points" element={<AuditCatalogPage />} />
            <Route path="report" element={<AuditReportPage />} />
            <Route path="schools/:schoolId" element={<AuditSchoolPage />} />
            <Route path="schools/:schoolId/report" element={<AuditReportPage />} />
          </Route>
          <Route path="email" element={<RequireAdmin permission="email.view"><GmailPage /></RequireAdmin>} />
          <Route path="chatbot" element={<RequireAdmin permission="chatbot.view"><ChatbotAdminPage /></RequireAdmin>} />
          <Route path="config" element={<RequireAdmin permission="config.view"><AdminConfigPage /></RequireAdmin>} />
          <Route path="kids" element={<RequireAdmin permission="kids.view"><KidsPage /></RequireAdmin>} />
          <Route path="support" element={<RequireAdmin permission="support.view"><SupportPage /></RequireAdmin>} />
          <Route path="resources/onboarding" element={<RequireAdmin permission="resources.view"><LocalzReviewPage /></RequireAdmin>} />
          <Route path="resources/onboarding/:requestId" element={<RequireAdmin permission="resources.view"><LocalzReviewDetailPage /></RequireAdmin>} />
          <Route path="resources/listings/:serviceId" element={<RequireAdmin permission="resources.view"><LocalzListingAdminPage /></RequireAdmin>} />
          <Route path="users" element={<RequireAdmin superOnly><UsersRolesPage /></RequireAdmin>} />
          <Route path="api-keys" element={<RequireAdmin superOnly><ApiKeysPage /></RequireAdmin>} />
          <Route path="api-keys/approve" element={<RequireAdmin superOnly><ApproveApiKeyPage /></RequireAdmin>} />
          <Route path="secret-requests" element={<RequireAdmin superOnly><SecretRequestsPage /></RequireAdmin>} />
          <Route path="audit-log" element={<RequireAdmin superOnly><AuditLogPage /></RequireAdmin>} />
          <Route path="secret-requests/approve" element={<RequireAdmin superOnly><ApproveSecretRequestPage /></RequireAdmin>} />
        </Route>
      </Route>
    </FaroRoutes>
  );
}

// /contact/submit was the upload form's old home, where a link was the
// default; /upload leads with the file.
function LegacySubmitRedirect() {
  const { search } = useLocation();
  const wantsFile = new URLSearchParams(search).get("kind") === "file";
  return <Navigate to={wantsFile ? "/upload" : "/upload?kind=link"} replace />;
}

export default function App() {
  useEffect(() => preloadWhenIdle(NEXT_TAPS, IS_PRERENDER), []);
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
