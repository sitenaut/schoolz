import asyncio

from services import lunch_menu
from services.lunch_menu import _classify_abbreviated_pdf_link, _classify_pdf_link, _classify_unbanded_pdf_link


def test_classifies_elementary_lunch():
    result = _classify_pdf_link(".../September2026-ES-Lunch.pdf")
    assert result == {
        "school_type": "elementary",
        "meal_type": "lunch",
        "period_label": "September 2026",
        "pdf_url": ".../September2026-ES-Lunch.pdf",
        "_sort": (2026, 8),
    }


def test_classifies_middle_breakfast_despite_real_district_typo():
    # Confirmed real filename from the district: "Setember" not "September".
    result = _classify_pdf_link(".../Setember2026-MS-Breakfast.pdf")
    assert result["school_type"] == "middle"
    assert result["meal_type"] == "breakfast"


def test_high_school():
    result = _classify_pdf_link(".../September2026-HS-Lunch.pdf")
    assert result["school_type"] == "high"


def test_unrelated_pdf_is_ignored():
    assert _classify_pdf_link(".../parent-handbook.pdf") is None


def test_classifies_audubon_elementary_lunch_no_hyphens():
    # Confirmed real filename from Audubon: no hyphens, band spelled out, "Menu" suffix.
    result = _classify_pdf_link(".../September2026ElementaryLunchMenu.pdf")
    assert result == {
        "school_type": "elementary",
        "meal_type": "lunch",
        "period_label": "September 2026",
        "pdf_url": ".../September2026ElementaryLunchMenu.pdf",
        "_sort": (2026, 8),
    }


def test_classifies_audubon_combined_jh_hs_lunch():
    result = _classify_pdf_link(".../September2026JH-HSLunchMenu.pdf")
    assert result["school_type"] == "high"
    assert result["meal_type"] == "lunch"


def test_classifies_audubon_prek_lunch():
    result = _classify_pdf_link(".../September2026PreKLunchMenu.pdf")
    assert result["school_type"] == "other"


def test_unbanded_skips_spreadsheet_siblings():
    assert _classify_unbanded_pdf_link(".../September2026_lunch_spreadsheet.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../September_2026_Breakfast.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../October2026-Preschool.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../NOV2026PreKMenu.pdf", "elementary") is None
    assert _classify_unbanded_pdf_link(".../October2026-Lunch.pdf", "elementary")["period_label"] == "October 2026"
    assert _classify_unbanded_pdf_link(".../September_2026.pdf", "elementary")["period_label"] == "September 2026"


def test_classifies_merchantville_abbreviated_month_and_year():
    # Confirmed real filenames from merchantvilleschool.org's /cafeteria page.
    lunch = _classify_abbreviated_pdf_link(".../MERSept26LunchMenu_1.pdf", "elementary")
    assert (lunch["meal_type"], lunch["period_label"], lunch["_sort"]) == ("lunch", "September 2026", (2026, 8))
    breakfast = _classify_abbreviated_pdf_link(".../MERSept2026BreakfastMenu.pdf", "elementary")
    assert (breakfast["meal_type"], breakfast["period_label"]) == ("breakfast", "September 2026")


def test_abbreviated_menu_skips_spanish_twin_and_unrelated():
    assert _classify_abbreviated_pdf_link(".../MERSept26LunchMenuSPA_1.pdf", "elementary") is None
    assert _classify_abbreviated_pdf_link(".../MERSept2026BreakfastMenuSPA.pdf", "elementary") is None
    assert _classify_abbreviated_pdf_link(".../26-27Calendar.pdf", "elementary") is None


def test_abbreviated_menus_keep_both_meals_and_latest_month(monkeypatch):
    html = (
        '<a href="/f/MERSept2099BreakfastMenu.pdf"></a><a href="/f/MERSept99LunchMenu_1.pdf"></a>'
        '<a href="/f/MEROct99LunchMenu.pdf"></a><a href="/f/MERSept99LunchMenuSPA_1.pdf"></a>'
        '<a href="/f/MERJan20LunchMenu.pdf"></a>'
    )

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x", school_types=["elementary"]))
    assert {(e["meal_type"], e["pdf_url"]) for e in found} == {
        ("breakfast", "http://x/f/MERSept2099BreakfastMenu.pdf"),
        ("lunch", "http://x/f/MERSept99LunchMenu_1.pdf"),
        ("lunch", "http://x/f/MEROct99LunchMenu.pdf"),
    }


def test_unbanded_menu_serves_every_school_type(monkeypatch):
    html = (
        '<a href="/f/January_2020.pdf"></a><a href="/f/September_2099.pdf"></a><a href="/f/October_2099.pdf"></a>'
        '<a href="/f/October_2099_lunch_spreadsheet.pdf"></a>'
    )

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x", school_types=["elementary", "middle", "other"]))
    assert sorted(e["school_type"] for e in found) == ["elementary", "elementary", "middle", "middle", "other", "other"]
    assert {e["pdf_url"] for e in found} == {"http://x/f/September_2099.pdf", "http://x/f/October_2099.pdf"}


def test_banded_discovery_picks_latest_month_whatever_the_link_order(monkeypatch):
    # The page can list two months at once; the set of links has no order, so
    # the winner used to be arbitrary per process.
    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    names = ["September2026-ES-Lunch.pdf", "October2026-ES-Lunch.pdf", "September2026-HS-Lunch.pdf"]
    for order in (names, list(reversed(names))):
        html = "".join(f'<a href="/f/{n}"></a>' for n in order)

        async def fake_fetch(url, html=html, **kw):
            return {"html": html}

        monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
        found = asyncio.run(lunch_menu.discover_current_menus("http://x"))
        assert {(e["school_type"], e["period_label"]) for e in found} == {("elementary", "October 2026"), ("high", "September 2026")}
        assert all("_sort" not in e for e in found)


def test_unbanded_menu_with_spaces_and_cache_buster():
    # Runnemede: "OCTOBER  2026  Menu.pdf", href-encoded, newer files carry ?rnd=.
    c = _classify_unbanded_pdf_link("/ourpages/auto/2025/10/14/47945897/OCTOBER%20%202026%20%20Menu.pdf", "elementary")
    assert c["period_label"] == "October 2026" and c["_sort"] == (2026, 9)
    c = _classify_unbanded_pdf_link("/x/SEPTEMBER%20%202026%20%20Menu.pdf?rnd=1787590730626", "elementary")
    assert c["period_label"] == "September 2026"


def test_drive_iframe_menus_are_found_by_their_drive_title(monkeypatch):
    # Gibbsboro embeds each menu as a Drive viewer; the filename lives only
    # in Drive's own page title.
    html = (
        '<iframe src="https://drive.google.com/file/d/AAAAAAAAAAAAAAAAAAAA/preview"></iframe>'
        '<iframe src="https://drive.google.com/file/d/BBBBBBBBBBBBBBBBBBBB/preview"></iframe>'
        '<a href="https://drive.google.com/file/d/CCCCCCCCCCCCCCCCCCCC/view">Budget</a>'
    )

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    async def fake_drive(html):
        return {
            "https://drive.google.com/uc?export=download&id=AAAAAAAAAAAAAAAAAAAA": "October 2099 monthly menu.pdf",
            "https://drive.google.com/uc?export=download&id=BBBBBBBBBBBBBBBBBBBB": "10-11 Menu.pdf",
            "https://drive.google.com/uc?export=download&id=CCCCCCCCCCCCCCCCCCCC": "Advertised Budget 2025-2026",
        }

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    monkeypatch.setattr(lunch_menu, "_resolve_drive_links", fake_drive)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x", school_types=["elementary"]))
    assert [(e["school_type"], e["period_label"], e["pdf_url"]) for e in found] == [
        ("elementary", "October 2099", "https://drive.google.com/uc?export=download&id=AAAAAAAAAAAAAAAAAAAA")
    ]


def test_drive_link_regex_reads_iframes_and_anchors():
    html = '<iframe src="https://drive.google.com/file/d/1EsjbF3RpoY56tnjZkhVg1gOyPQwKcq0j/preview"></iframe>'
    assert lunch_menu._DRIVE_FILE_RE.findall(html) == ["1EsjbF3RpoY56tnjZkhVg1gOyPQwKcq0j"]


def test_hyphenated_yearless_menu_skips_the_prek_twin():
    ok = lunch_menu._classify_abbreviated_pdf_link("http://x/October-Lunch-Menu.pdf", "elementary")
    assert ok and ok["meal_type"] == "lunch" and ok["period_label"].startswith("October ")
    assert lunch_menu._classify_abbreviated_pdf_link("http://x/October-Pre-K-Lunch-Menu.pdf", "elementary") is None


def test_menu_table_of_drive_links_reads_month_meal_and_k8(monkeypatch):
    def cell(prek, k8):
        return (
            f'<td><h5><a href="https://drive.google.com/file/d/{prek * 20}/view">PreK</a> / '
            f'<a href="https://drive.google.com/file/d/{k8 * 20}/view">K-8</a></h5></td>'
        )

    html = (
        "<a href='https://x/2025-2026.pdf'>old</a><h4>2098-2099</h4><table>"
        "<tr><td><h4>MONTH</h4></td><td><h4>BREAKFAST</h4></td><td><h4>LUNCH</h4></td></tr>"
        f"<tr><td><h5><strong>September</strong></h5></td>{cell('A', 'B')}{cell('C', 'D')}</tr>"
        f"<tr><td><h5><strong>January</strong></h5></td>{cell('E', 'F')}<td></td></tr></table>"
    )

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x", school_types=["elementary"]))
    assert {(e["meal_type"], e["period_label"], e["pdf_url"][-20:]) for e in found} == {
        ("breakfast", "September 2098", "B" * 20),
        ("lunch", "September 2098", "D" * 20),
        ("breakfast", "January 2099", "F" * 20),
    }


def test_image_menu_links_are_classified_by_their_link_text():
    # Washington Township posts the current month as fixed-name PNGs; only the
    # link text ("... Menu -- October&nbsp;2026") says what each one is.
    from services.lunch_menu import _classify_image_menu_links

    html = (
        '<a href="/uploaded/Food_Service/ES_L.png">Elementary Lunch Menu -- October&nbsp;2026</a>'
        '<a href="/uploaded/Food_Service/HS.png"><span>High School Lunch Menu -- October 2026</span></a>'
        '<a href="/uploaded/Food_Service/PS_B.png">Preschool Breakfast Menu -- October 2026</a>'
        '<a href="/uploaded/Food_Service/MS.webp">Middle School Lunch Menu -- October 2026</a>'
        '<a href="/uploaded/logo.png">Our logo</a>'
    )
    got = {(c["school_type"], c["meal_type"]): c for c in _classify_image_menu_links("https://x.org/menus", html)}
    assert set(got) == {("elementary", "lunch"), ("high", "lunch"), ("other", "breakfast"), ("middle", "lunch")}
    assert got[("elementary", "lunch")]["pdf_url"] == "https://x.org/uploaded/Food_Service/ES_L.png"
    assert got[("elementary", "lunch")]["period_label"] == "October 2026"


def test_embedded_menu_pdfs_are_classified_by_their_own_heading():
    # Clayton's menus are iframe-embedded PDFs behind aptg.co short links, so
    # the PDF's heading (not its filename, which may have no month) classifies it.
    from services.lunch_menu import _MENU_SUBPAGE_RE, _classify_menu_heading

    got = {(c["school_type"], c["meal_type"]) for c in _classify_menu_heading("HS/MS Lunch Menu October 2026\nMONDAY", "https://aptg.co/x")}
    assert got == {("high", "lunch"), ("middle", "lunch")}
    herma = _classify_menu_heading("Herma Simmons Breakfast Menu October 2026", "https://aptg.co/y")
    assert [(c["school_type"], c["meal_type"], c["period_label"]) for c in herma] == [("elementary", "breakfast", "October 2026")]
    assert _classify_menu_heading("Pre-K BREAKFAST MENU October 2026", "u")[0]["school_type"] == "other"
    assert _classify_menu_heading("Welcome", "u") == []
    assert _MENU_SUBPAGE_RE.findall('{"link":"/o/cpsd/page/elementary-school-menus","x":"/o/cpsd/page/food-service"}') == ["/o/cpsd/page/elementary-school-menus"]


def test_coded_school_menu_filenames():
    from datetime import date

    from services.lunch_menu import _classify_coded_pdf_link as c

    today = date(2026, 10, 12)
    base = "https://x.example/ourpages/auto/2025/8/18/1/"
    a = c(base + "Oct%202026%20MS%20Lunch%20Menu.pdf?rnd=1", today)
    assert (a["school_type"], a["meal_type"], a["period_label"]) == ("middle", "lunch", "October 2026")
    b = c(base + "CS%20Sept%2027%20Lunch%20Menu.pdf", today)
    assert (b["school_type"], b["period_label"]) == ("elementary", "September 2026")
    assert c(base + "Oct%202026%20ECC%20Breakfast%20Menu.pdf", today)["school_type"] == "other"
    assert c(base + "October%202026%20Snacks.pdf", today) is None
    assert c(base + "Middle%20School%20Breakfast%20Menu.pdf", today) is None


def test_myschoolplate_location_links_classify_by_their_text():
    from services.lunch_menu import _classify_myschoolplate_link as c

    assert c("Elementary Lunch") == ("elementary", "lunch")
    assert c("Elementary Breakfast") == ("elementary", "breakfast")
    assert c("Stuart and Garfield Lunch") == ("other", "lunch")
    assert c("Twin Hills Grab & Go Breakfast") is None  # a one-off, not the school's menu
    assert c("Memorial and Bookbinder Lunch") is None  # the vendor API already covers middle/high


def test_price_legends_are_not_menu_days():
    from services.lunch_menu import _PRICE_BOX_RE

    assert _PRICE_BOX_RE.search("Lunch Meal Prices: $3.25 Elementary, $3.40 MSHS Student")
    assert not _PRICE_BOX_RE.search("Chicken Parmesan, Side of Pasta, Garden Tossed Salad")


def test_a_month_year_lunch_forms_pdf_is_the_unbanded_menu():
    from services.lunch_menu import _classify_unbanded_pdf_link

    found = _classify_unbanded_pdf_link("https://x.org/wp-content/uploads/October-2026-Lunch-Forms.pdf", "elementary")
    assert found["period_label"] == "October 2026" and found["school_type"] == "elementary"
    assert _classify_unbanded_pdf_link("https://x.org/wp-content/uploads/Lunch-Token-Form-25.pdf", "elementary") is None


def test_band_in_words_with_breakfast_in_the_name(monkeypatch):
    # Burlington City's real October names. Every one says "Breakfast", so
    # all were thrown out; September's MS-HS file got through on its typo
    # ("Breakfasat") as an unbanded menu and was served to the elementaries.
    names = [
        "September%202026%20MS-HS%20Breakfasat-Lunch%20Menu.pdf?rnd=1788896180931",
        "October%202026%20Elementary%20Breakfast%20-Lunch-%20Aftercare.pdf?rnd=1791382606607",
        "October%202026%20MS-HS%20Breakfast%20-Lunch-Aftercare%20Menu.pdf?rnd=1790625640458",
        "October%202026%20Pre-K%20Breakfast-%20Lunch-Aftercare%20Snack.pdf",
        "Birthday%20Flyer%2026-27.pdf",
    ]
    html = "".join(f'<a href="/ourpages/auto/2026/7/1/56872616/{n}"></a>' for n in names)

    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/apps/pages/", school_types=["elementary", "high", "middle"]))
    got = {(e["school_type"], e["meal_type"], e["period_label"], e["pdf_url"].split("%20")[2]) for e in found}
    # No Pre-K school in the district, so its PDF isn't parsed for nobody.
    assert got == {
        ("elementary", "lunch", "October 2026", "Elementary"),
        ("middle", "lunch", "October 2026", "MS-HS"),
        ("high", "lunch", "October 2026", "MS-HS"),
    }


def test_month_band_meal_filenames_with_no_year():
    # Riverside's /breakfast-lunch-menu document list.
    from datetime import date

    from services.lunch_menu import _classify_month_band_pdf_link as c

    today = date(2026, 10, 29)
    base = "https://files.smartsites.parentsquare.com/10346/"
    hsms = c(base + "oct_hsms_lunch_menu.pdf", today)
    assert sorted(x["school_type"] for x in hsms) == ["high", "middle"]
    assert {x["period_label"] for x in hsms} == {"October 2026"}
    elem = c(base + "nov_elementary_breakfast_menu.pdf", today)
    assert [(x["school_type"], x["meal_type"], x["period_label"]) for x in elem] == [("elementary", "breakfast", "November 2026")]
    assert c(base + "oct_prek_lunch_menu.pdf", today)[0]["school_type"] == "other"
    assert c(base + "October-Lunch-Menu.pdf", today) == []


def test_band_glued_to_the_month_with_no_year():
    # Kingsway's menus page.
    from datetime import date

    from services.lunch_menu import _classify_glued_band_pdf_link as c

    today = date(2026, 10, 29)
    base = "https://resources.finalsite.net/images/v1/kingswayk12njus/"
    hs = c(base + "HSOctoberLunchMenu.pdf", today)
    assert (hs["school_type"], hs["meal_type"], hs["period_label"]) == ("high", "lunch", "October 2026")
    ms = c(base + "MiddleSchoolBreakfastOctoberMenu.pdf", today)
    assert (ms["school_type"], ms["meal_type"]) == ("middle", "breakfast")
    assert c(base + "HSBreakfastNovemberMenu.pdf", today)["period_label"] == "November 2026"
    assert c(base + "OctoberLunchMenu.pdf", today) is None
    # South Harrison's K-6 lunch, no meal word.
    sh = c("https://x/OctoberK-6Menu.pdf", today)
    assert (sh["school_type"], sh["meal_type"], sh["period_label"]) == ("elementary", "lunch", "October 2026")
    assert c("https://x/OctoberPreKMenu.pdf", today) is None
    # Logan: band, meal, year, month.
    lg = c("https://x/LOG%20Middle%20Lunch%20Menu%202026%20OCT.pdf", today)
    assert (lg["school_type"], lg["meal_type"], lg["period_label"]) == ("middle", "lunch", "October 2026")
    assert c("https://x/LOG ELEM Lunch Menu 2026 OCT.pdf", today)["school_type"] == "elementary"
    assert c("https://x/FED PRE-K & K Lunch Menu 2026 OCT.pdf", today) is None


# --- districts whose menus are pictures or scans (see services/menu_filenames.py) ---


def _page(monkeypatch, html: str, drive: dict | None = None, api_urls: set | None = None):
    async def fake_fetch(url, **kw):
        return {"html": html}

    async def fake_rm(url, html):
        return set()

    async def fake_drive(html):
        return drive or {}

    async def fake_api(url, html):
        return api_urls or set()

    monkeypatch.setattr(lunch_menu.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(lunch_menu, "_resolve_resource_manager_links", fake_rm)
    monkeypatch.setattr(lunch_menu, "_resolve_drive_links", fake_drive)
    monkeypatch.setattr(lunch_menu, "_apptegy_document_urls", fake_api)


def test_mantuas_unnamed_band_files_serve_every_school(monkeypatch):
    _page(
        monkeypatch,
        '<a href="/ourpages/auto/2099/10/1/9/2099_Oct_Breakfast_2.pdf?rnd=1">Open in new tab</a>'
        '<a href="/ourpages/auto/2099/10/1/9/october%20rough%20lunch.pdf?rnd=2">Open in new tab</a>',
    )
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/cafeteria", school_types=["elementary"]))
    # The lunch file names no year, so it is read as the nearest October.
    assert sorted((e["meal_type"], e["period_label"].split()[0], e["school_type"]) for e in found) == [
        ("breakfast", "October", "elementary"),
        ("lunch", "October", "elementary"),
    ]


def test_elks_drive_titles_are_read_and_its_prek_twin_is_not_a_school_here(monkeypatch):
    drive = {
        "https://drive.google.com/uc?id=K6": "K-6 Aura LunchMenu_2099-10-OCT.pptx.png",
        "https://drive.google.com/uc?id=PK": "PREK-V-LunchMenu_2099-10-OCT.pptx.png",
        "https://drive.google.com/uc?id=ST": "Static Breakfast Menu (2).pptx.pdf",
        "https://drive.google.com/uc?id=PO": "8500 Food Services (M).pdf",
    }
    _page(monkeypatch, "<html></html>", drive=drive)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/menus", school_types=["elementary"]))
    assert [(e["school_type"], e["meal_type"], e["pdf_url"]) for e in found] == [("elementary", "lunch", "https://drive.google.com/uc?id=K6")]


def test_a_file_named_for_one_school_is_that_schools_alone(monkeypatch):
    # Swedesboro-Woolwich: three schools share the ELEM menu, Hill has its own, breakfast is for all.
    schools = [
        {"id": "s1", "name": "Margaret Clifford School", "short_name": "Clifford", "school_type": "elementary"},
        {"id": "s2", "name": "Charles Stratton School", "short_name": "Stratton", "school_type": "elementary"},
        {"id": "s3", "name": "Walter Hill School", "short_name": "Hill", "school_type": "elementary"},
    ]
    base = "https://resources.finalsite.net/images/v1/swe"
    _page(
        monkeypatch,
        "".join(
            f'<a href="{base}/SWE-{name}-{month}2099.pdf">x</a>'
            for month in ("OCT", "NOV")
            for name in ("ELEMLUNCHMENU", "HILLLUNCHMENU", "ALLBREAKFASTMENU")
        ),
    )
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/menus", school_types=["elementary"], schools=schools))
    got = sorted((e["meal_type"], e["period_label"], e.get("school_id") or "", e["pdf_url"].rsplit("/", 1)[-1]) for e in found)
    assert got == [
        ("breakfast", "November 2099", "", "SWE-ALLBREAKFASTMENU-NOV2099.pdf"),
        ("breakfast", "October 2099", "", "SWE-ALLBREAKFASTMENU-OCT2099.pdf"),
        ("lunch", "November 2099", "", "SWE-ELEMLUNCHMENU-NOV2099.pdf"),
        ("lunch", "November 2099", "s3", "SWE-HILLLUNCHMENU-NOV2099.pdf"),
        ("lunch", "October 2099", "", "SWE-ELEMLUNCHMENU-OCT2099.pdf"),
        ("lunch", "October 2099", "s3", "SWE-HILLLUNCHMENU-OCT2099.pdf"),
    ]
    assert all(e["school_type"] == "elementary" for e in found)


def test_a_school_named_file_does_not_hide_the_districts_own(monkeypatch):
    # Township of Franklin: the lunch menu is for every school; Janvier alone has a breakfast menu.
    schools = [
        {"id": "a", "name": "Mary F. Janvier School", "short_name": "Janvier", "school_type": "elementary"},
        {"id": "b", "name": "Main Road School", "short_name": "Main Road", "school_type": "elementary"},
    ]
    api = {
        "https://files.x/d/FTS-OCT-2099-Janvier-BreakfastMenu.pdf?disposition=inline",
        "https://files.x/d/FTS-LunchMenu_2099-10-OCT.pdf?disposition=inline",
    }
    _page(monkeypatch, "<html></html>", api_urls=api)
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/documents/lunch/572162", school_types=["elementary"], schools=schools))
    assert sorted((e["meal_type"], e.get("school_id")) for e in found) == [("breakfast", "a"), ("lunch", None)]


def test_deptfords_secondary_menu_is_for_the_middle_and_high_school_only(monkeypatch):
    _page(
        monkeypatch,
        '<a href="https://deptfordschools.org/Lunch%20Menus/26-27/Elementary%20Menu%20October%202099.pdf">x</a>'
        '<a href="https://deptfordschools.org/Lunch%20Menus/26-27/Secondary%20Menu%20October%202099.pdf">x</a>',
    )
    found = asyncio.run(lunch_menu.discover_current_menus("http://x/lunchmenus", school_types=["elementary", "high", "middle", "other"]))
    assert sorted((e["school_type"], e["pdf_url"].rsplit("/", 1)[-1]) for e in found) == [
        ("elementary", "Elementary%20Menu%20October%202099.pdf"),
        ("high", "Secondary%20Menu%20October%202099.pdf"),
        ("middle", "Secondary%20Menu%20October%202099.pdf"),
    ]


def test_apptegy_documents_folder_lists_files_its_html_does_not(monkeypatch):
    html = '<script>fetch("https://thrillshare-cmsv2.services.thrillshare.com/api/v2/s/355780/documents")</script>'
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"documents": [{"url": "https://files.x/FTS-LunchMenu_2099-10-OCT.pdf?disposition=inline"}, {"file_name": "no url"}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            seen["call"] = (url, params)
            return FakeResponse()

    monkeypatch.setattr(lunch_menu.httpx, "AsyncClient", FakeClient)
    page = "https://www.franklintwpschools.org/documents/parents-students/district-menus/572162"
    assert asyncio.run(lunch_menu._apptegy_document_urls(page, html)) == {"https://files.x/FTS-LunchMenu_2099-10-OCT.pdf?disposition=inline"}
    assert seen["call"] == ("https://thrillshare-cmsv2.services.thrillshare.com/api/v2/s/355780/documents", {"folder_id": "572162"})
    # A page whose script names no documents API, or whose URL names no folder, is left alone.
    assert asyncio.run(lunch_menu._apptegy_document_urls(page, "<html></html>")) == set()
    assert asyncio.run(lunch_menu._apptegy_document_urls("https://x/documents", html)) == set()


def test_a_school_name_that_begins_like_a_month_is_not_one():
    # "Janvier" is a Township of Franklin school, not January.
    assert _classify_abbreviated_pdf_link("https://x/FTS-OCT-2026-Janvier-BreakfastMenu.pdf", "elementary") is None
    assert _classify_abbreviated_pdf_link("https://x/January2026LunchMenu.pdf", "elementary")["period_label"] == "January 2026"
    assert _classify_abbreviated_pdf_link("https://x/SEPTLUNCHMENU.pdf", "elementary")["period_label"].startswith("September")


def test_a_dated_menus_prompt_is_the_one_stored_extractions_are_keyed_on(monkeypatch):
    # Every stored menu read is keyed by a hash of this prompt: rewording it makes
    # each one be paid for again, so the text of a dated menu's prompt is pinned.
    import hashlib

    from services import page_extractions

    seen = []

    async def fake_bytes(*a, **k):
        return "x", b"%PDF-1.4 fake"

    async def fake_read(url, content, prompt):
        seen.append(prompt)
        return []

    async def stored(key):
        return None

    async def store(key, value):
        pass

    monkeypatch.setattr(lunch_menu.scraper_client, "get_bytes", fake_bytes)
    monkeypatch.setattr(lunch_menu, "_read_menu_file", fake_read)
    monkeypatch.setattr(lunch_menu, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(page_extractions, "stored", stored)
    monkeypatch.setattr(page_extractions, "store", store)
    for label, meal in (("October 2026", "lunch"), ("October 2026", None), ("May 2027", "breakfast"), (None, "lunch")):
        asyncio.run(lunch_menu.parse_menu_pdf("http://x/a.pdf", label, meal))
    assert [hashlib.sha1(p.encode()).hexdigest()[:12] for p in seen[:3]] == ["a431b07b68a5", "5bcacac3926c", "f40852593344"]
    assert "the month and year are printed on it" in seen[3]


def test_apptegy_page_pictures_belong_to_the_heading_in_their_column():
    def heading(text):
        return {"component": "ts-heading", "config": {"content": f"<h1>{text}</h1>"}}

    def image(url):
        return {"component": "ts-image", "config": {"image": {"url": url}}}

    content = {
        "component": "BASE_COLUMN",
        "config": [
            [{"component": "ts-two-column", "config": [[heading("MES Breakfast Menu")], [heading("MES Lunch Menu")]]}],
            [{"component": "ts-two-column", "config": [[image("b1.jpeg"), image("b2.jpeg")], [image("l1.jpeg"), image("l2.jpeg")]]}],
            [{"component": "ts-image", "config": {"image": {"url": "orphan.jpeg"}}}],
        ],
    }
    assert lunch_menu._apptegy_page_media(content) == [
        ("MES Breakfast Menu", "b1.jpeg"),
        ("MES Breakfast Menu", "b2.jpeg"),
        ("MES Lunch Menu", "l1.jpeg"),
        ("MES Lunch Menu", "l2.jpeg"),
    ]


def test_undated_pictures_are_each_a_candidate_and_dated_titles_still_filter_by_month():
    from datetime import date

    items = [
        {"title": "PES Lunch Menu", "extension": "jpeg", "url": "a.jpeg", "undated": True},
        {"title": "PES Lunch Menu", "extension": "jpeg", "url": "b.jpeg", "undated": True},
        {"title": "October 2026 Lunch", "extension": "pdf", "url": "old.pdf"},
        {"title": "November 2026 Lunch", "extension": "pdf", "url": "new.pdf"},
        {"title": "PES Lunch Menu", "extension": "jpeg", "url": "c.jpeg"},  # untitled by a month and not marked undated
    ]
    got = lunch_menu.pick_presence_menus(items, date(2026, 11, 3))
    assert sorted(c["url"] for c in got) == ["a.jpeg", "b.jpeg", "new.pdf"]
