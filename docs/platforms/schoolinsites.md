# SchoolInSites / ConnectSuite

Greenwich Township (Gloucester County). Same rules as the other platform files: when you confirm a new shape, add it here in the same PR.

- **Tells**: assets on `content.schoolinsites.com` and `content.myconnectsuite.com`, a "SCHOOLinSITES" footer badge, requirejs `/js/widgets/*.js`. Flat page slugs (`/calendars`, `/transportation`, `/staff`, `/about`, `/contact`); one instance serves the district plus a subdomain per school. Pages are server-rendered; missing ones are a real 404.
- **robots.txt disallows `/sys/` for every agent but Googlebot**, and `/sys/` holds the calendar export and the directory API, so neither is wired. The calendar comes from the board-approved PDF on `/calendars` instead (`calendar_pdf_url`).
- **Documents** are `content.myconnectsuite.com/api/documents/<32-hex>[.pdf]`; the filename is only in `Content-Disposition`, so `find_pdf_link` picks the calendar by its link text ("Printable District Calendar"). Track the linking page.
- **Calendar export** (for reference): the Export button opens `/sys/calendar/ical?widgetId=<id>&type=Calendar`, which shows `webcal://<host>/sys/calendar/export?widgetId=<id>&type=1`; homepage "upcoming" widgets export with `type=2`. Its UIDs are random on every request, so wiring it would need title-and-start keys (as the Smart Sites `generateCalendarICS.php` feeds get).
- **Staff directory** is a widget filled from `/sys/api/directory?widgetId=&viewId=contactlist-1&pageNum=1&pageSize=<n>` (JSON: `NameFirstLast`, `JobTitle`, `Department`, `PhoneNumber`; email only through a form). Not read.
- `school_info.scan` finds neither address nor phone (the footer is plain text), so type them into the seed.
