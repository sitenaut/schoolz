# Weebly

Beverly City (one PK-8 school). Same rules as the other platform files: when you confirm a new shape, add it here in the same PR.

- **Tells**: assets from `cdn*.editmysite.com`, `/files/main_style.css`, pages at `/<slug>.html`. `/site-map.html` lists every page and is the best crawl entry. Plain curl works.
- **Uploads** are `/uploads/<a>/<b>/<c>/<d>/<siteid>/<lowercased_filename>.pdf`; a re-upload gets a `__1_` suffix, so filenames change year to year: track the page that links them.
- **Layout**: content is `#wsite-content`, sections `h2.wsite-content-title`, columns `table.wsite-multicol-table` (layout, not a data table). There is no `<header>`: the logo is `#logo .wsite-logo img` (also `og:image`), and the footer address is plain text in `#footer-wrap`, so `school_info.scan` finds neither and warns; type both into the seed.
- **Emails** are Cloudflare-obfuscated (`/cdn-cgi/l/email-protection#<hex>`, `data-cfemail`); `staff_roster._decode_cf_email` reads them. Beverly's staff page (`/faculty-and-staff-contact-information.html`, multicol blocks under grade headings) has no parser yet.
- **Scanned PDFs**: Beverly's calendar and 76-page handbook have no text layer, so only the model's native PDF reading gets anything. The calendar's event list puts labels and dates in separate columns, and the model has paired "Parent Teacher Conference" with the "November 5 & 6 SCHOOL CLOSED" row in most runs.
