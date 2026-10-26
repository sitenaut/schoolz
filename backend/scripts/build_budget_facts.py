"""Build the budgets import file from a checkout of the NJ school-funding audit.

    python3 backend/scripts/build_budget_facts.py <audit repo checkout> <rev27.csv> [--out FILE]

Reads, at the checkout's current commit (which must be clean):
  data/processed/district_panel.csv   the state figures, one row per district (all of NJ)
  research/districts/*/<code>-*.md     the per-district profiles
the state's own UFB revenue file for the budget year (rev27.csv: it isn't in the audit's
git history, so it is passed in and its SHA-256 recorded), and from this repo:
  seed/njdoe/NJPubSchool.csv               the state's district names
  seed/budget/nj_districts.json            our districts and their NJDOE codes
  seed/budget/nj_2026_27_statements.json   hand-picked quotes from district documents

Writes seed/budget/nj_2026_27.json, which POST /admin/budget/import takes as is.
Standard library only, so it runs on the host. Rules that decide what is published
live here, not in the import:
  - a figure is left out where the audit flags it as not comparable (a partial
    benefits line, aid that isn't the state formula figure);
  - levy dollars are kept only where they give the panel's own percentage;
  - audited health costs only where the audit reconciled both years against the
    state's benefits figures;
  - quotes are kept only for a district whose profile is "Consistent" or
    "Confirmed" at high or medium confidence, and each must appear verbatim in
    a [primary] bullet of the profile's "What the district says" section, its
    link in that section and off nj.gov (the district's own document). A quote
    that fails stops the build: it means the profile changed under it.
The profile check is not enough on its own: profiles have paraphrased inside quotation
marks, so a new quote is read in the district's own document before it goes in the
statements file.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parent.parent
SEED = BACKEND / "seed" / "budget"
STATE_DIRECTORY = BACKEND / "seed" / "njdoe" / "NJPubSchool.csv"
BUDGET_YEAR = "2026-27"
# district_panel.csv column names at this budget year
COLS = {
    "benefits_prior": "benefits_budget_2526",
    "benefits_budget": "benefits_budget_2627",
    "other_spending_prior": "other_gce_budget_2526",
    "other_spending_budget": "other_gce_budget_2627",
    "fund_balance_prior": "fund_balance_used_2526",
    "fund_balance_budget": "fund_balance_used_2627",
}
# (year label, panel column, audited report column) for each health-cost year,
# and the same for staffing. The audited reports are for fiscal years ending June 30.
HEALTH_YEARS = (("2022-23", "acfr_health_2023", "acfr_2023_source", "acfr_quality_2023"),
                ("2024-25", "acfr_health_2025", "acfr_2025_source", "acfr_quality_2025"))
STAFFING_YEARS = (("2021-22", "students_per_teacher_2021_22"), ("2024-25", "students_per_teacher_2024_25"))
SALARY = ("2024-25", "median_teacher_salary_2024_25")
LEVY_LINE = "114"  # Total Tax Levy
UFB_REPORT = "https://www.nj.gov/education/budget/ufb/2627/reports/{county}/UFB27_{code}.pdf"
AID_FILE = "https://www.nj.gov/education/stateaid/2627/FY27_GBM_District_Details.xlsx"
STAFFING_SOURCE = "https://www.nj.gov/education/spr/download/"
QUALIFYING_LABELS = ("Consistent", "Confirmed")
QUALIFYING_CONFIDENCE = ("high", "medium")
# Districts in the panel with no school in the state's school directory (no
# schools of their own, or a services commission), named by hand.
NAMES = {
    "0050": "Allenhurst School District",
    "0695": "Camden County Educational Services Commission",
    "0730": "Cape May Point School District",
    "2130": "Hi-Nella School District",
    "2320": "Interlaken School District",
    "2780": "Longport School District",
    "3364": "Educational Services Commission of Morris County",
    "3580": "Newfield School District",
    "3800": "Ocean Gate School District",
    "3975": "Northern Region Educational Services Commission",
    "4500": "Rockleigh School District",
    "5700": "West Wildwood School District",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def dollars(v: str) -> int | None:
    return round(float(v)) if v not in ("", None) else None


def number(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {heading}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def bullets(sec: str) -> list[str]:
    """Top-level bullets, each with its indented continuation lines."""
    out: list[str] = []
    for line in sec.splitlines():
        if line.startswith("- "):
            out.append(line)
        elif out and line.startswith("  "):
            out[-1] += "\n" + line
    return out


def qualifies(profile: str) -> bool:
    assessment = section(profile, "Assessment").lstrip()
    confidence = re.search(r"<!-- facts:.*?confidence=(\w+)", profile)
    return assessment.startswith(tuple(f"**{label}" for label in QUALIFYING_LABELS)) and bool(
        confidence and confidence.group(1) in QUALIFYING_CONFIDENCE
    )


def check_statement(code: str, profile: str, st: dict) -> None:
    said = section(profile, "What the district")
    host = urlparse(st["url"]).hostname or ""
    if host == "nj.gov" or host.endswith(".nj.gov"):
        sys.exit(f"{code}: {st['url']} is a state document, not the district's own")
    if st["url"] not in said:
        sys.exit(f"{code}: {st['url']} is not cited in the profile's 'What the district says'")
    hits = [b for b in bullets(said) if squash(st["quote"]) in squash(b)]
    if not any(b.startswith("- [primary]") for b in hits):
        sys.exit(f"{code}: quote not found verbatim in a [primary] bullet: {st['quote']!r}")


def state_names() -> dict[str, str]:
    """District code -> the state's name for it. The directory is Latin-1, with
    a preamble before the header and codes written as ="0800"."""
    lines = STATE_DIRECTORY.read_text(encoding="latin-1").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("County Code,"))
    names: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        code = re.sub(r'[="]', "", row["District Code"])
        names.setdefault(code, row["District Name"].strip())
    return names


def levies(rev27: Path) -> dict[str, tuple[int, int]]:
    """District code -> (prior year revised, budget year) total tax levy."""
    out: dict[str, tuple[int, int]] = {}
    for row in csv.DictReader(open(rev27)):
        if row["line_no"] == LEVY_LINE:
            out[row["district_id"]] = (round(float(row["amount_2"])), round(float(row["amount_3"])))
    return out


def health_costs(p: dict) -> dict | None:
    if not all(p[quality] == "reconciled" and p[col] for _, col, _, quality in HEALTH_YEARS):
        return None
    (y0, c0, u0, _), (y1, c1, u1, _) = HEALTH_YEARS
    return {"start": {"year": y0, "value": dollars(p[c0]), "url": p[u0]}, "end": {"year": y1, "value": dollars(p[c1]), "url": p[u1]}}


def staffing(p: dict) -> dict | None:
    ratios = [(year, number(p[col])) for year, col in STAFFING_YEARS]
    salary = dollars(p[SALARY[1]])
    if all(v is None for _, v in ratios) and salary is None:
        return None
    (y0, r0), (y1, r1) = ratios
    return {
        "students_per_teacher": {"start": {"year": y0, "value": r0}, "end": {"year": y1, "value": r1}} if r0 and r1 else None,
        "median_teacher_salary": {"year": SALARY[0], "value": salary} if salary else None,
        "url": STAFFING_SOURCE,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path, help="checkout of the NJ school-funding audit repo")
    ap.add_argument("rev27", type=Path, help="the state's UFB revenue file for the budget year (rev27.csv)")
    ap.add_argument("--out", type=Path, default=SEED / "nj_2026_27.json")
    args = ap.parse_args()

    if git(args.repo, "status", "--porcelain", "--", "data/processed", "research"):
        sys.exit("the audit checkout has uncommitted changes under data/processed or research")
    commit = git(args.repo, "rev-parse", "HEAD")
    panel = list(csv.DictReader(open(args.repo / "data" / "processed" / "district_panel.csv")))
    ours = {d["state_code"]: d["name"] for d in json.loads((SEED / "nj_districts.json").read_text())["districts"]}
    quotes = json.loads((SEED / "nj_2026_27_statements.json").read_text())["districts"]
    official = state_names()
    levy = levies(args.rev27)

    missing = sorted(set(ours) - {p["district_id"] for p in panel})
    if missing:
        sys.exit(f"our districts missing from the panel: {missing}")

    # A slug is the state's name for the district; two districts with the same
    # name (there are several Washington Townships) also get their county.
    names = {p["district_id"]: official.get(p["district_id"]) or NAMES.get(p["district_id"]) for p in panel}
    unnamed = sorted(code for code, name in names.items() if not name)
    if unnamed:
        sys.exit(f"no name for {unnamed}: add them to NAMES")
    seen: dict[str, int] = {}
    for name in names.values():
        seen[slugify(name)] = seen.get(slugify(name), 0) + 1

    rows, quoted, levy_left_out = [], [], []
    for p in sorted(panel, key=lambda r: r["district_id"]):
        code = p["district_id"]
        slug = slugify(names[code])
        if seen[slug] > 1:
            slug = f"{slug}-{slugify(p['county'])}"
        row = {
            "state": "NJ",
            "state_code": code,
            # Ours where we track the district, so the import finds it by name
            # and the page reads like the school pages; the state's otherwise.
            "name": ours.get(code, names[code]),
            "county": p["county"],
            "slug": slug,
            "comparable": p["comparable"] == "True",
            "prior_basis": "revised" if p["baseline_source"] == "revised" else "original",
        }
        if p["benefits_line_incomplete"] != "True":
            for field in ("benefits_prior", "benefits_budget", "other_spending_prior", "other_spending_budget"):
                row[field] = dollars(p[COLS[field]])
        if p["aid_source"] == "formula":
            row["formula_aid_change"] = dollars(p["state_aid_change_dollars"])
            row["aid_source_url"] = AID_FILE
        row["levy_change_pct"] = number(p["levy_change_pct"])
        if code in levy and row["levy_change_pct"] is not None:
            prior, budget = levy[code]
            if prior and round((budget - prior) / prior * 100, 1) == round(row["levy_change_pct"], 1):
                row["levy_prior"], row["levy_budget"] = prior, budget
            else:
                levy_left_out.append(code)
        row["fund_balance_prior"] = dollars(p[COLS["fund_balance_prior"]])
        row["fund_balance_budget"] = dollars(p[COLS["fund_balance_budget"]])
        row["budget_report_url"] = UFB_REPORT.format(county=p["county_id"], code=code)
        row["health_costs"] = health_costs(p)
        row["staffing"] = staffing(p)
        profiles = list((args.repo / "research" / "districts").glob(f"*/{code}-*.md"))
        statements = quotes.get(code, [])
        if statements and len(profiles) == 1 and qualifies(profile := profiles[0].read_text()):
            for st in statements:
                check_statement(code, profile, st)
            row["statements"] = statements
            quoted.append(code)
        elif statements:
            print(f"{code} {row['name']}: profile no longer qualifies, quotes left out", file=sys.stderr)
        rows.append(row)

    if levy_left_out:
        print(f"levy dollars left out (don't give the panel's percentage): {levy_left_out}", file=sys.stderr)
    out = {
        "source_commit": commit,
        "budget_year": BUDGET_YEAR,
        "levy_file_sha256": hashlib.sha256(args.rev27.read_bytes()).hexdigest(),
        "districts": rows,
    }
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"{len(rows)} districts ({len(quoted)} with quotes, {sum(1 for r in rows if r['state_code'] in ours)} ours) from commit {commit[:7]} -> {args.out.name}")


if __name__ == "__main__":
    main()
