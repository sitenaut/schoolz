from services.staff_roster import _parse_ednet_page, _parse_edlio_page, _parse_eschoolview_page, _parse_page

_CARD_WITH_TITLE = """
<div class="fsConstituentItem" data-constituent-id="4990">
    <h3 class="fsFullName"><a>Eda Abramovitz</a></h3>
    <div class="fsTitles"><strong>Titles:</strong> Spanish</div>
    <div class="fsEmail"><a href="mailto:eabramovitz@chclc.org">x</a></div>
    <div class="fsPhones"><a href="tel:(856) 667-3303">(856) 667-3303</a></div>
</div>
"""

_CARD_WITHOUT_TITLE = """
<div class="fsConstituentItem" data-constituent-id="3001">
    <h3 class="fsFullName"><a>Evelyn Acevedo-Ortiz</a></h3>
    <div class="fsEmail"><a href="mailto:eortiz@chclc.org">x</a></div>
</div>
"""


def test_parses_full_card():
    items = _parse_page(_CARD_WITH_TITLE)
    assert len(items) == 1
    item = items[0]
    assert item["constituent_id"] == "4990"
    assert item["full_name"] == "Eda Abramovitz"
    assert item["title"] == "Spanish"
    assert item["email"] == "eabramovitz@chclc.org"
    assert item["phone"] == "(856) 667-3303"


def test_missing_title_is_none_not_empty_string():
    items = _parse_page(_CARD_WITHOUT_TITLE)
    assert len(items) == 1
    assert items[0]["title"] is None
    assert items[0]["phone"] is None


def test_multiple_cards_on_one_page():
    items = _parse_page(_CARD_WITH_TITLE + _CARD_WITHOUT_TITLE)
    assert len(items) == 2
    assert {i["constituent_id"] for i in items} == {"4990", "3001"}


_EDNET_PAGE = """
<div id="staff"><div class="staff-category"><div class="staff-header"><h1>Administration</h1></div>
<ul class="staff-categoryStaffMembers">
<li class="staff-categoryStaffMember"><a href="/apps/pages/index.jsp?uREC_ID=1566560&type=u" title="Administration">
<script>StaffPhotoCom.writeTemplate({who: " Warren Danenza"});</script>
<dl class="staffPhotoWrapperRound"><dt> Warren Danenza </dt><dd> Principal </dd></dl></a></li>
<li class="staff-categoryStaffMember"><a href="/apps/pages/index.jsp?uREC_ID=1553487&type=u">
<dl class="staffPhotoWrapperRound"><dt> Lauren  Orfe </dt></dl></a></li>
</ul></div>
<div class="staff-category"><div class="staff-header"><h1>School Nurses</h1></div>
<ul class="staff-categoryStaffMembers">
<li class="staff-categoryStaffMember"><a href="/apps/pages/index.jsp?uREC_ID=77&type=u">
<dl><dt>Pat Nurse</dt><dd>School Nurse</dd></dl></a></li>
</ul></div></div>
"""


def test_ednet_cards_take_department_from_category_header():
    items = _parse_ednet_page(_EDNET_PAGE)
    assert [i["full_name"] for i in items] == ["Warren Danenza", "Lauren Orfe", "Pat Nurse"]
    assert items[0]["constituent_id"] == "ednet:1566560"
    assert items[0]["title"] == "Principal"
    assert items[0]["department"] == "Administration"
    assert items[2]["department"] == "School Nurses"


def test_ednet_missing_title_is_none_and_no_contact_fields():
    item = _parse_ednet_page(_EDNET_PAGE)[1]
    assert item["title"] is None
    assert item["email"] is None and item["phone"] is None


def test_ednet_ignores_finalsite_pages():
    assert _parse_ednet_page(_CARD_WITH_TITLE) == []


_ESCHOOLVIEW_PAGE = """
<div class="col-md-3 col-xs-12"><div><span class="scName">Zataveski, Lori</span></div>
<div><span class="scTitle">Principal</span></div></div>
<div class="col-md-3 col-xs-12"><div><span class="scName">Zataveski, Lori</span></div>
<div><span class="scTitle">Principal</span></div></div>
<div class="col-md-3 col-xs-12"><div><span class="scName">Brown, Ashley</span></div>
<div><span class="scTitle"></span></div></div>
"""


def test_eschoolview_flips_last_first_and_collapses_repeated_cards():
    items = _parse_eschoolview_page(_ESCHOOLVIEW_PAGE)
    assert [i["full_name"] for i in items] == ["Lori Zataveski", "Ashley Brown"]
    assert items[0]["title"] == "Principal"
    assert items[0]["email"] is None and items[0]["phone"] is None


def test_eschoolview_blank_title_is_none_and_other_markup_is_empty():
    assert _parse_eschoolview_page(_ESCHOOLVIEW_PAGE)[1]["title"] is None
    assert _parse_eschoolview_page(_CARD_WITH_TITLE) == []


_EDLIO_CARDS = """
<ul><li class="staff" id="staff_1_0"><div class="user-info"><div class="name-position">
  <a class="name" href="/apps/pages/index.jsp?uREC_ID=1547201&amp;type=u">Katie  Bash</a>
  <span class="user-position user-data">1st Grade</span></div>
  <div class="email-phone"><span class="user-email"><a class="email" href="/apps/email/index.jsp?uREC_ID=1547201">Email Katie Bash</a></span>
  <a class="user-phone" href="tel:Ext. 6217">Ext. 6217</a></div></div></li>
<li class="staff" id="staff_2_0"><div class="user-info"><div class="name-position">
  <a class="name" href="/apps/pages/index.jsp?uREC_ID=1568196&amp;type=u">Jill Brown</a></div></div></li>
<li class="staff"><div class="user-info">no link</div></li></ul>
"""


def test_edlio_cards_have_stable_ids_titles_and_no_contact_fields():
    items = _parse_edlio_page(_EDLIO_CARDS)
    assert [i["constituent_id"] for i in items] == ["edlio:1547201", "edlio:1568196"]
    assert items[0]["full_name"] == "Katie Bash" and items[0]["title"] == "1st Grade"
    assert items[1]["title"] is None
    assert all(i["email"] is None and i["phone"] is None for i in items)
    assert _parse_edlio_page(_CARD_WITH_TITLE) == []


def test_sibling_school_titles_are_dropped_from_a_shared_roster():
    from services.staff_roster import drop_sibling_school_staff

    def p(name, title):
        return {"constituent_id": name, "full_name": name, "title": title}

    roster = [
        p("a", "Director of Curriculum/Nokomis School Principal"),
        p("b", "Superintendent/Neeta Principal"),
        p("c", "Neeta Nurse"),
        p("d", "School Counselor"),
        p("e", None),
    ]
    kept, dropped = drop_sibling_school_staff(roster, ["Neeta", "Neeta School"], [["Nokomis", "Nokomis School"]])
    assert [e["constituent_id"] for e in kept] == ["b", "c", "d", "e"]
    assert [e["constituent_id"] for e in dropped] == ["a"]
    # No sibling on the site (or none with a distinctive name): nothing is dropped.
    assert drop_sibling_school_staff(roster, ["Neeta"], []) == (roster, [])
    # A title naming both schools is shared staff and stays.
    both = [p("f", "Nurse, Neeta and Nokomis")]
    assert drop_sibling_school_staff(both, ["Neeta"], [["Nokomis"]]) == (both, [])
