from services.staff_roster import _parse_ednet_page, _parse_page

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
