type PermUser = { is_admin: boolean; permissions?: string[] } | null | undefined;

/** Super admins hold every permission; the server already expands that in
 * `permissions`, the `is_admin` check just keeps the UI right in the
 * moment before /auth/me resolves. */
export function can(user: PermUser, permission: string): boolean {
  return !!user && (user.is_admin || (user.permissions ?? []).includes(permission));
}

/** Anyone who should see an admin surface at all. */
export function isStaff(user: PermUser): boolean {
  return !!user && (user.is_admin || (user.permissions ?? []).length > 0);
}

export const ADMIN_TABS: { to: string; label: string; permission: string | null }[] = [
  { to: "/admin/inbox", label: "Inbox", permission: "inbox.view" },
  { to: "/admin/newsletters", label: "Newsletters", permission: "newsletters.manage" },
  { to: "/admin/scans", label: "Scans", permission: "scans.view" },
  { to: "/admin/chatbot", label: "Chatbot", permission: "chatbot.view" },
  { to: "/admin/config", label: "Import/export", permission: "config.view" },
  { to: "/admin/kids", label: "Kids", permission: "kids.view" },
  { to: "/admin/users", label: "Users & roles", permission: null },
  { to: "/admin/api-keys", label: "API keys", permission: null },
];

/** null permission = super admin only. */
export function visibleAdminTabs(user: PermUser) {
  return ADMIN_TABS.filter((t) => (t.permission === null ? !!user?.is_admin : can(user, t.permission)));
}
