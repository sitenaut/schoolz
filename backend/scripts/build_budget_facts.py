"""Build the budget-section import file from a checkout of the NJ school-funding audit.

    python3 backend/scripts/build_budget_facts.py <audit repo checkout> [--out FILE]

Reads, at the checkout's current commit (which must be clean):
  data/processed/district_panel.csv   the state figures, one row per district
  research/districts/*/<code>-*.md     the per-district profiles
and from this repo:
  seed/budget/nj_districts.json            our districts and their NJDOE codes
  seed/budget/nj_2026_27_statements.json   hand-picked quotes from district documents

Writes seed/budget/nj_2026_27.json, which POST /admin/budget/import takes as is.
Standard library only, so it runs on the host. Rules that decide what is published
live here, not in the import:
  - a figure is left out where the audit flags it as not comparable (a partial
    benefits line, aid that isn't the state formula figure);
  - quotes are kept only for a district whose profile is "Consistent" or
    "Confirmed" at high or medium confidence, and each must appear verbatim in
    a [primary] bullet of the profile's "What the district says" section, its
    link in that section and off nj.gov (the district's own document). A quote
    that fails stops the build: it means the profile changed under it.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

SEED = Path(__file__).resolve().parent.parent / "seed" / "budget"
BUDGET_YEAR = "2026-27"
# district_panel.csv column names at this budget year
COLS = {
    "benefits_prior": "benefits_budget_2526",
    "benefits_budget": "benefits_budget_2627",
    "fund_balance_prior": "fund_balance_used_2526",
    "fund_balance_budget": "fund_balance_used_2627",
}
UFB_REPORT = "https://www.nj.gov/education/budget/ufb/2627/reports/{county}/UFB27_{code}.pdf"
AID_FILE = "https://www.nj.gov/education/stateaid/2627/FY27_GBM_District_Details.xlsx"
QUALIFYING_LABELS = ("Consistent", "Confirmed")
QUALIFYING_CONFIDENCE = ("high", "medium")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def dollars(v: str) -> int | None:
    return round(float(v)) if v not in ("", None) else None


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path, help="checkout of the NJ school-funding audit repo")
    ap.add_argument("--out", type=Path, default=SEED / "nj_2026_27.json")
    args = ap.parse_args()

    if git(args.repo, "status", "--porcelain", "--", "data/processed", "research"):
        sys.exit("the audit checkout has uncommitted changes under data/processed or research")
    commit = git(args.repo, "rev-parse", "HEAD")
    panel = {r["district_id"]: r for r in csv.DictReader(open(args.repo / "data" / "processed" / "district_panel.csv"))}
    ours = json.loads((SEED / "nj_districts.json").read_text())["districts"]
    quotes = json.loads((SEED / "nj_2026_27_statements.json").read_text())["districts"]

    rows, missing, quoted = [], [], []
    for d in ours:
        code = d["state_code"]
        p = panel.get(code)
        if not p:
            missing.append(f"{code} {d['name']}")
            continue
        row = {"state": "NJ", "state_code": code, "name": d["name"]}
        if p["benefits_line_incomplete"] != "True":
            row.update(
                benefits_prior=dollars(p[COLS["benefits_prior"]]),
                benefits_budget=dollars(p[COLS["benefits_budget"]]),
                prior_basis="revised" if p["baseline_source"] == "revised" else "original",
            )
        if p["aid_source"] == "formula":
            row["formula_aid_change"] = dollars(p["state_aid_change_dollars"])
            row["aid_source_url"] = AID_FILE
        row["levy_change_pct"] = float(p["levy_change_pct"]) if p["levy_change_pct"] else None
        row["fund_balance_prior"] = dollars(p[COLS["fund_balance_prior"]])
        row["fund_balance_budget"] = dollars(p[COLS["fund_balance_budget"]])
        row["budget_report_url"] = UFB_REPORT.format(county=p["county_id"], code=code)
        profiles = list((args.repo / "research" / "districts").glob(f"*/{code}-*.md"))
        statements = quotes.get(code, [])
        if statements and len(profiles) == 1 and qualifies(profile := profiles[0].read_text()):
            for st in statements:
                check_statement(code, profile, st)
            row["statements"] = statements
            quoted.append(code)
        elif statements:
            print(f"{code} {d['name']}: profile no longer qualifies, quotes left out", file=sys.stderr)
        rows.append(row)

    args.out.write_text(json.dumps({"source_commit": commit, "budget_year": BUDGET_YEAR, "districts": rows}, indent=1) + "\n")
    print(f"{len(rows)} districts ({len(quoted)} with quotes) from commit {commit[:7]} -> {args.out.name}")
    for m in missing:
        print(f"not in the panel: {m}", file=sys.stderr)


if __name__ == "__main__":
    main()
