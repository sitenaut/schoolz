from services.staff_roster import _parse_page

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
