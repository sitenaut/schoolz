import importlib.util
import json
import os
import uuid
import zipfile
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import District, DistrictBudget, School, User
from schemas import BudgetImport

SEED = Path(__file__).resolve().parent.parent / "seed" / "budget"
_spec = importlib.util.spec_from_file_location("build_budget_facts", Path(__file__).resolve().parent.parent / "scripts" / "build_budget_facts.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


async def _admin(client: AsyncClient) -> dict:
    run_id = uuid.uuid4().hex[:8]
    email = f"admin_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"admin_{run_id}", "password": "password123"})
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


async def _district_with_school(tag: str, code: str | None = None) -> tuple[str, str]:
    async with database.SessionLocal() as db:
        district = District(name=f"Budget District {tag}", state="NJ", state_code=code)
        db.add(district)
        await db.flush()
        school = School(name=f"Budget School {tag}", slug=f"budget-school-{tag}", district_id=district.id, school_type="elementary")
        # A private preschool filed under the district for the town picker.
        db.add_all([school, School(name=f"Budget Preschool {tag}", slug=f"budget-preschool-{tag}", district_id=district.id, school_type="other")])
        await db.commit()
        return district.name, school.slug


def _row(code: str, name: str | None = None, **figures) -> dict:
    return {"state_code": code, "name": name, "slug": f"district-{code.lower()}", "county": "Testcounty", "comparable": True,
            "benefits_prior": 1_000_000, "benefits_budget": 1_200_000, "formula_aid_change": -50_000,
            "levy_change_pct": 4.5, "fund_balance_prior": 300_000, "fund_balance_budget": 0,
            "budget_report_url": f"https://www.nj.gov/education/budget/ufb/2627/reports/07/UFB27_{code}.pdf", **figures}


QUOTE = {"topic": "Health benefits", "quote": "Health costs rose", "source": "Budget presentation", "url": "https://district.example/budget.pdf", "date": "2026-03-17"}


@pytest.mark.anyio
async def test_import_sets_the_state_code_by_name_and_the_school_page_shows_the_figures():
    tag = uuid.uuid4().hex[:8]
    code = f"T{tag[:6].upper()}"  # never a real NJDOE code, so it can't meet a real district
    name, slug = await _district_with_school(tag)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        r = await client.post("/admin/budget/import", headers=headers, json={
            "source_commit": "1af77f0", "budget_year": "2026-27",
            "districts": [_row(code, name, statements=[QUOTE]), _row("TNONE", "Not tracked here")]})
        assert r.status_code == 200, r.text
        assert r.json() == {"created": 2, "updated": 0, "codes_set": 1, "tracked": 1, "state_districts_created": 2}

        page = await client.get(f"/schools/{slug}/budget")  # public: no auth header
        assert page.status_code == 200
        body = page.json()
        assert body["district_name"] == name and body["budget_year"] == "2026-27"
        assert body["slug"] == f"district-{code.lower()}"
        assert (body["benefits_prior"], body["benefits_budget"], body["formula_aid_change"]) == (1_000_000, 1_200_000, -50_000)
        assert body["statements"] == [QUOTE]
        # A preschool filed under the district for the picker isn't one of its schools.
        assert (await client.get(f"/schools/budget-preschool-{tag}/budget")).json() is None

        # Same year again: matched by the code now, figures and quotes replaced.
        r = await client.post("/admin/budget/import", headers=headers, json={
            "source_commit": "2386bf9", "budget_year": "2026-27", "districts": [_row(code, levy_change_pct=6.0)]})
        assert r.json()["updated"] == 1 and r.json()["codes_set"] == 0
        body = (await client.get(f"/schools/{slug}/budget")).json()
        assert body["levy_change_pct"] == 6.0 and body["statements"] == []


@pytest.mark.anyio
async def test_latest_budget_year_wins_and_a_name_never_takes_a_second_code():
    tag = uuid.uuid4().hex[:8]
    name, slug = await _district_with_school(tag)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        code = f"T{tag[:6].upper()}"
        for year, levy in (("2026-27", 2.0), ("2025-26", 9.0)):
            r = await client.post("/admin/budget/import", headers=headers, json={
                "source_commit": "abcdef0", "budget_year": year, "districts": [_row(code, name, levy_change_pct=levy)]})
            assert r.status_code == 200, r.text
        assert (await client.get(f"/schools/{slug}/budget")).json()["budget_year"] == "2026-27"

        other = await client.post("/admin/budget/import", headers=headers, json={
            "source_commit": "abcdef0", "budget_year": "2026-27", "districts": [_row(f"U{tag[:6].upper()}", name)]})
        # The second code gets a /budgets page of its own, tied to none of ours.
        assert other.json()["tracked"] == 0 and other.json()["codes_set"] == 0
        assert (await client.get(f"/budgets/district-u{tag[:6].lower()}")).json()["schools"] == []


@pytest.mark.anyio
async def test_no_budget_on_file_is_null_and_import_needs_admin():
    tag = uuid.uuid4().hex[:8]
    _, slug = await _district_with_school(tag)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/schools/{slug}/budget")
        assert r.status_code == 200 and r.json() is None
        denied = await client.post("/admin/budget/import", json={"source_commit": "abcdef0", "budget_year": "2026-27", "districts": []})
        assert denied.status_code == 401


@pytest.mark.anyio
async def test_budgets_pages_list_every_district_with_medians_from_comparable_ones_only():
    tag = uuid.uuid4().hex[:6].upper()
    county = f"County {tag}"
    name, school_slug = await _district_with_school(tag.lower())
    rows = [
        _row(f"A{tag}", name, county=county, levy_change_pct=2.0),
        _row(f"B{tag}", "Second", county=county, levy_change_pct=4.0, benefits_budget=1_100_000),
        _row(f"C{tag}", "Third", county=county, levy_change_pct=9.0),
        # Left out of every median, though it has a page.
        _row(f"D{tag}", "Commission", county=county, levy_change_pct=50.0, comparable=False),
    ]
    rows[0]["staffing"] = {"students_per_teacher": {"start": {"year": "2021-22", "value": 11.0}, "end": {"year": "2024-25", "value": 12.0}},
                           "median_teacher_salary": None, "url": "https://www.nj.gov/education/spr/download/"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        r = await client.post("/admin/budget/import", headers=headers, json={"source_commit": "abcdef0", "budget_year": "2026-27", "districts": rows})
        assert r.status_code == 200, r.text

        index = (await client.get("/budgets")).json()  # public
        mine = {d["slug"]: d for d in index["districts"] if d["county"] == county}
        assert set(mine) == {f"district-{c}{tag.lower()}" for c in "abcd"}
        assert mine[f"district-a{tag.lower()}"]["tracked"] and not mine[f"district-b{tag.lower()}"]["tracked"]
        assert mine[f"district-b{tag.lower()}"]["benefits_change_pct"] == 10.0

        page = (await client.get(f"/budgets/district-a{tag.lower()}")).json()
        assert page["name"] == name and page["schools"] == [{"slug": school_slug, "name": f"Budget School {tag.lower()}"}]
        assert page["staffing"]["students_per_teacher"]["end"]["value"] == 12.0
        # Median of 2, 4 and 9 - the commission's 50 isn't counted.
        assert page["medians"]["levy_change_pct"]["county"] == 4.0
        assert page["medians"]["levy_change_pct"]["state"] is not None
        # Only one district has staffing figures: too few for a median.
        assert page["medians"]["students_per_teacher"]["county"] is None

        assert (await client.get("/budgets/no-such-district")).status_code == 404


@pytest.mark.anyio
async def test_a_slug_never_changes_and_a_row_from_before_state_districts_is_adopted():
    tag = uuid.uuid4().hex[:6].upper()
    code = f"T{tag}"
    name, _ = await _district_with_school(tag.lower(), code=code)
    async with database.SessionLocal() as db:
        district = (await db.execute(District.__table__.select().where(District.name == name))).first()
        db.add(DistrictBudget(district_id=district.id, budget_year="2026-27", source_commit="abcdef0", statements=[]))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        first = await client.post("/admin/budget/import", headers=headers, json={"source_commit": "abcdef0", "budget_year": "2026-27", "districts": [_row(code, name)]})
        assert first.json()["created"] == 0 and first.json()["updated"] == 1
        again = await client.post("/admin/budget/import", headers=headers, json={
            "source_commit": "abcdef0", "budget_year": "2026-27", "districts": [_row(code, "Renamed", slug="a-new-slug")]})
        assert again.json()["state_districts_created"] == 0
        assert (await client.get(f"/budgets/district-{code.lower()}")).json()["name"] == "Renamed"
        assert (await client.get("/budgets/a-new-slug")).status_code == 404


def test_committed_import_file_matches_the_schema_and_quotes_only_district_documents():
    data = BudgetImport.model_validate(json.loads((SEED / "nj_2026_27.json").read_text()))
    codes = [d.state_code for d in data.districts]
    assert len(codes) == len(set(codes))
    slugs = [d.slug for d in data.districts]
    assert len(slugs) == len(set(slugs)) and all(slugs)
    for d in data.districts:
        for s in d.statements:
            assert not (s.url.split("/")[2].endswith("nj.gov")), s.url


PROFILE = """# Somewhere (Camden County) — district 0001

## What the district / local reporting says
- [primary] The deck says "Health costs rose" by a lot. [Budget presentation](https://district.example/budget.pdf)
- [news] A paper said "Taxes went up". [Paper](https://paper.example/story)

## Assessment
**Consistent.** Something.

<!-- facts: confidence=medium; plan=unknown -->
"""


def test_builder_accepts_a_verbatim_primary_quote():
    assert builder.qualifies(PROFILE)
    builder.check_statement("0001", PROFILE, QUOTE)


@pytest.mark.parametrize("change", [
    {"quote": "Health costs soared"},                                       # not verbatim
    {"quote": "Taxes went up", "url": "https://paper.example/story"},       # a news bullet
    {"url": "https://www.nj.gov/education/budget/ufb/x.pdf"},               # a state document
    {"url": "https://district.example/other.pdf"},                          # not cited in the profile
])
def test_builder_refuses_a_quote_the_profile_does_not_support(change):
    with pytest.raises(SystemExit):
        builder.check_statement("0001", PROFILE, {**QUOTE, **change})


def test_builder_only_quotes_well_supported_profiles():
    assert not builder.qualifies(PROFILE.replace("confidence=medium", "confidence=low"))
    assert not builder.qualifies(PROFILE.replace("**Consistent.**", "**Insufficient evidence.**"))


def test_builder_keeps_audited_health_costs_only_where_both_years_reconcile():
    row = {"acfr_health_2023": "100.0", "acfr_health_2025": "120.0", "acfr_quality_2023": "reconciled", "acfr_quality_2025": "reconciled",
           "acfr_2023_source": "https://www.nj.gov/a23.pdf", "acfr_2025_source": "https://www.nj.gov/a25.pdf"}
    assert builder.health_costs(row)["end"] == {"year": "2024-25", "value": 120, "url": "https://www.nj.gov/a25.pdf"}
    assert builder.health_costs({**row, "acfr_quality_2023": "unreconciled"}) is None
    assert builder.health_costs({**row, "acfr_quality_2025": "reconciled (not used)"}) is None


def _aid(start: int, end: int, limit: float | None = None) -> dict:
    return {"k12": {"start": {"year": "2025-26", "value": start}, "end": {"year": "2026-27", "value": end}},
            "categories": [{"key": "equalization", "start": 0, "end": end - start}, {"key": "transportation", "start": start, "end": start}],
            "limit_pct": limit, "preschool": None}


def _idea(start: int, end: int) -> dict:
    return {"start": {"year": "2025-26", "value": start}, "end": {"year": "2026-27", "value": end}, "private_school_share": 1_000, "preliminary": True}


@pytest.mark.anyio
async def test_state_aid_and_the_idea_grant_are_stored_with_their_medians():
    tag = uuid.uuid4().hex[:6].upper()
    county = f"County {tag}"
    rows = [
        _row(f"A{tag}", "First", county=county, state_aid=_aid(1_000_000, 970_000, -3.0), idea_grant=_idea(100_000, 101_000)),
        _row(f"B{tag}", "Second", county=county, state_aid=_aid(1_000_000, 1_060_000, 6.0)),
        _row(f"C{tag}", "Third", county=county, state_aid=_aid(1_000_000, 1_020_000)),
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        r = await client.post("/admin/budget/import", headers=headers, json={"source_commit": "abcdef0", "budget_year": "2026-27", "districts": rows})
        assert r.status_code == 200, r.text
        page = (await client.get(f"/budgets/district-a{tag.lower()}")).json()
        assert page["state_aid"]["limit_pct"] == -3.0 and page["state_aid"]["categories"][0] == {"key": "equalization", "start": 0, "end": -30_000}
        assert page["idea_grant"]["private_school_share"] == 1_000 and page["idea_grant"]["preliminary"] is True
        # Median of -3, +6 and +2; only one district has an IDEA grant, too few for a median.
        assert page["medians"]["state_aid_change_pct"]["county"] == 2.0
        assert page["medians"]["idea_change_pct"]["county"] is None
        assert (await client.get(f"/budgets/district-b{tag.lower()}")).json()["idea_grant"] is None


def test_committed_aid_figures_agree_with_the_panel_change():
    data = json.loads((SEED / "nj_2026_27.json").read_text())
    assert data["state_files_sha256"] and all(len(v) == 64 for v in data["state_files_sha256"].values())
    for d in data["districts"]:
        aid = d.get("state_aid")
        assert (aid is not None) == (d.get("formula_aid_change") is not None), d["state_code"]
        if aid:
            assert aid["k12"]["end"]["value"] - aid["k12"]["start"]["value"] == d["formula_aid_change"]
            assert sum(c["end"] for c in aid["categories"]) == aid["k12"]["end"]["value"]
            assert aid["limit_pct"] in (None, -3.0, 6.0)


def _categories(eq: int, sped: int, choice: int = 0) -> dict:
    return {"categories": {**dict.fromkeys((key for _, key in builder.AID_CATEGORIES), 0), "equalization": eq, "special_education": sped, "school_choice": choice}}


def test_builder_finds_a_district_held_at_the_aid_limit():
    prior = _categories(400_000, 600_000)
    assert builder.limit_pct(prior, _categories(388_001, 582_001)) == -3.0  # each category rounded after the limit
    assert builder.limit_pct(prior, _categories(424_000, 636_000, choice=90_000)) == 6.0  # school choice aid isn't limited
    assert builder.limit_pct(prior, _categories(390_000, 590_000)) is None
    assert builder.limit_pct(_categories(0, 0), _categories(0, 0)) is None


def test_builder_stops_when_the_two_aid_files_disagree():
    aid = {"2025-26": {"0001": {"total": 100, "prior_total": 90, **_categories(100, 0)}},
           "2026-27": {"0001": {"total": 97, "prior_total": 99, **_categories(97, 0)}}}
    with pytest.raises(SystemExit):
        builder.state_aid("0001", aid, {"2025-26": {}, "2026-27": {}})
    aid["2026-27"]["0001"]["prior_total"] = 100
    out = builder.state_aid("0001", aid, {"2025-26": {}, "2026-27": {}})
    assert out["categories"] == [{"key": "equalization", "start": 100, "end": 97}] and out["preschool"] is None


def _xlsx(path, rows: list[list]) -> object:
    """A one-sheet workbook with inline strings, the way the state's files store text."""
    def cell(ref: str, v) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>' if isinstance(v, str) else f'<c r="{ref}"><v>{v}</v></c>'
    body = "".join(f'<row r="{i}">' + "".join(cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(r)) + "</row>" for i, r in enumerate(rows, 1))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>')
    return path


IDEA_HEADER = ["County Name", "County Code", "District Code", "District Name", "Basic Grant Ages \n3 to 21", "Basic Grant Nonpublic Share",
               "Preschool Grant Ages  3 to 5", "Preschool Grant Nonpublic Share"]


def test_builder_reads_idea_awards_and_leaves_out_charter_schools(tmp_path):
    path = _xlsx(tmp_path / "idea.xlsx", [
        ["SFY 2027 IDEA Basic and Preschool Grant Awards"], ["as of June 23, 2026- preliminary"], IDEA_HEADER,
        ["Camden", 7, 800, "Somewhere Township", 2_000_000, 300_000, 100_000, 0],
        # Charter rows: the FY27 file has their county one row out, and one school twice.
        ["Mercer", 80, 8140, "A Charter School", 90_000, 0, 1_000, 0],
        ["Hudson", 80, 8140, "A Charter School", 91_000, 0, 1_000, 0],
    ])
    preliminary, awards = builder.idea_awards(path)
    assert preliminary is True
    assert awards == {"0800": {"total": 2_100_000, "private_school_share": 300_000}}


def test_builder_stops_on_a_district_listed_twice_or_a_missing_column(tmp_path):
    row = ["Camden", 7, 800, "Somewhere Township", 2_000_000, 0, 0, 0]
    with pytest.raises(SystemExit):
        builder.idea_awards(_xlsx(tmp_path / "twice.xlsx", [IDEA_HEADER, row, row]))
    with pytest.raises(SystemExit):
        builder.idea_awards(_xlsx(tmp_path / "renamed.xlsx", [[*IDEA_HEADER[:4], "Basic Grant"], row]))
