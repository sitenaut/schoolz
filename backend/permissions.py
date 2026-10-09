"""The fixed catalog of things an admin role can be granted.

Roles (rows) are data an admin edits; permissions are code, because each one
names a set of endpoints that must actually check it. A super admin
(`User.is_admin`) implicitly holds every permission and is the only one who
can manage users and roles - those are deliberately not in this catalog, so
no role can ever be granted the power to mint more admins.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    access: str  # "read" | "write"
    sensitive: bool = False


PERMISSIONS: tuple[Permission, ...] = (
    # Read: see the data and run history, change nothing.
    Permission("inbox.view", "Contact inbox", "Read messages sent through the public contact form.", "read"),
    Permission("scans.view", "Scheduled scans", "See scheduled jobs and their run history.", "read"),
    Permission("email.view", "Gmail & email scanners", "See connected inboxes, email scanners and captured school emails.", "read"),
    Permission("submissions.view", "Community submissions", "See submitted sources and their attachments.", "read"),
    Permission("analytics.view", "Analytics & survey", "View page-visit reports, the campaign report and survey responses.", "read"),
    Permission("chatbot.view", "Chatbot settings", "See which providers/models the chatbot uses.", "read"),
    Permission("kids.view", "Kids view admin", "Admin tools for the Kids view (capture page kinds).", "read"),
    Permission("config.view", "Export config", "Download the full district/school/job configuration.", "read"),
    Permission("audit.view", "Data audit", "See the data audit and the missing-data reports (district wording only), download and print them.", "read"),
    # Write: change things. Each implies the matching read permission.
    Permission("schools.manage", "Schools & districts", "Create/edit schools, districts and high-school class pages; run their scans.", "write"),
    Permission("newsletters.manage", "Newsletters", "Add, edit, re-run and delete Smore newsletter sources.", "write"),
    Permission("scans.manage", "Scheduled scans", "Create, edit, run and delete scheduled jobs.", "write"),
    Permission("email.manage", "Gmail & email scanners", "Connect/disconnect inboxes, create, edit and run email scanners.", "write"),
    Permission("inbox.manage", "Contact inbox", "Mark messages read/unread and delete them.", "write"),
    Permission("submissions.manage", "Community submissions", "Approve, edit and delete submitted sources.", "write"),
    Permission("chatbot.manage", "Chatbot settings", "Switch chatbot providers/models and run comparisons.", "write"),
    Permission("audit.manage", "Data audit", "See the internal audit wording, run a data point's scans, and mark data points as not published.", "write"),
    Permission("seasonal.manage", "Seasonal guides", "Add, edit and delete the seasonal guide links and attractions (haunts, light shows, Santa) behind the season badge.", "write"),
    Permission(
        "config.manage",
        "Import config",
        "Import a full configuration. Effectively edits everything above.",
        "write",
        sensitive=True,
    ),
)

PERMISSION_KEYS: frozenset[str] = frozenset(p.key for p in PERMISSIONS)


def expand(granted: set[str]) -> set[str]:
    """`x.manage` implies `x.view` (when that exists), so a role that can
    change something can always see it."""
    out = set(granted)
    for key in granted:
        if key.endswith(".manage"):
            view = key[: -len(".manage")] + ".view"
            if view in PERMISSION_KEYS:
                out.add(view)
    return out
