# Data Audit Portal — design mockups

Exported artboards from the Design canvas for the admin data audit. They are
mockups: every status, count, school override and "why" note in them is
hard-coded sample data, not real coverage. The real page computes those from
the database and scan history.

| File | Screen |
|---|---|
| `Main.dc.html` | Audit by school — school × data-point grid, summary tiles, filters, selected-cell detail |
| `Catalog.dc.html` | Audit by data point — one row per data point with source, cadence, freshness window, compliance |
| `School.dc.html` | One school's audit — tabs for needs attention / current / not applicable |
| `DistrictReport.dc.html` | Printable missing-data report for a district (or the current filters) |
| `SchoolReport.dc.html` | Printable missing-data report for one school |

Each file is a Design Component page: markup inside `<x-dc>`, `{{holes}}`
filled by the `renderVals()` script at the bottom. `support.js` is the design
tool's runtime and is not included; read the markup and script, don't try to
open them in a browser.

Rules the mockups encode:

- Statuses: **current**, **stale**, **failing**, **not collecting**, **not applicable**.
  Not applicable is left out of the compliance score.
- Stale = two missed scheduled runs plus a grace period (window per cadence is
  on the Catalog screen). Hand-entered data with no scan is stale when not
  confirmed this school year.
- Applicability is by `school_type` (e.g. day rotation and morning
  announcements are high-school only; preschool team is preschool only).
