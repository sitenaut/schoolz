"""Which child each Backpack Capture page goes to (services/capture_routing.py)."""
from services.capture_routing import Child, name_matches, route

MAYA = Child("s-maya", "1111111", "Maya", "Smith")
BEN = Child("s-ben", "2222222", "Ben", "Smith")
FAMILY = [MAYA, BEN]


def _classroom(name: str | None, email: str | None, account_index: int | None = 2, **extra) -> dict:
    header = f"[aria-label] Google Account: {name}\n({email}) (role=button)\n" if name else ""
    return {
        "adapter": "classroom",
        "source_url": f"https://classroom.google.com/u/{account_index}/h",
        "account_index": account_index,
        "reduced_text": header + "ALGEBRA I",
        "status": "ok",
        **extra,
    }


def _genesis(studentid: str | None) -> dict:
    query = f"&studentid={studentid}" if studentid else ""
    return {
        "adapter": "genesis",
        "source_url": f"https://parents.example.org/genesis/parents?tab1=studentdata&tab2=gradebook{query}",
        "reduced_text": "Course Summary",
        "status": "ok",
    }


def _placed(routing) -> dict[str, int]:
    return {sid: len(caps) for sid, caps in routing.by_student.items()}


def test_genesis_goes_by_its_studentid_and_never_to_a_stranger():
    routing = route([_genesis("2222222"), _genesis("1111111"), _genesis("9999999")], FAMILY)
    assert _placed(routing) == {"s-ben": 1, "s-maya": 1}
    assert len(routing.unrouted) == 1
    assert routing.unrouted_accounts == []  # only Classroom logins are worth asking about


def test_numeric_classroom_login_decides_even_against_a_hint():
    routing = route(
        [
            _classroom("Maya Smith", "1111111@chclc.org"),
            _classroom("Someone Else", "7777777@chclc.org", account_index=3, student_hint="s-ben"),
        ],
        FAMILY,
    )
    assert _placed(routing) == {"s-maya": 1}
    [other] = routing.unrouted_accounts
    assert (other.account_index, other.email, other.other_student) == (3, "7777777@chclc.org", True)


def test_account_name_places_a_page_when_the_email_says_nothing():
    routing = route([_classroom("Smith, Ben", "ben.smith@school.org")], FAMILY)
    assert _placed(routing) == {"s-ben": 1}


def test_hint_places_a_login_the_name_cannot():
    routing = route([_classroom("Benny S", "bsmith27@school.org", student_hint="s-ben")], FAMILY)
    assert _placed(routing) == {"s-ben": 1}
    # A hint naming someone else's child is no hint at all.
    routing = route([_classroom("Benny S", "bsmith27@school.org", student_hint="s-stranger")], FAMILY)
    [unknown] = routing.unrouted_accounts
    assert (unknown.name, unknown.other_student, unknown.captures) == ("Benny S", False, 1)


def test_pages_without_a_login_follow_their_google_account():
    headless = _classroom(None, None, account_index=2)
    routing = route([headless, _classroom("Maya Smith", "maya@school.org", account_index=2)], FAMILY)
    assert _placed(routing) == {"s-maya": 2}


def test_only_child_takes_what_cannot_be_anyone_else():
    only = [MAYA]
    routing = route([_genesis(None), _classroom(None, None)], only)
    assert _placed(routing) == {"s-maya": 2}
    # ...but not a Classroom login under another name: that may be a parent's
    # own account (a teacher's classes), so the extension asks instead.
    routing = route([_classroom("Pat Smith", "pat.smith@district.org", account_index=0)], only)
    assert routing.by_student == {}
    [parent] = routing.unrouted_accounts
    assert (parent.account_index, parent.name, parent.other_student) == (0, "Pat Smith", False)


def test_name_matching_ignores_order_case_and_accents():
    assert name_matches("SMITH, MAYA", MAYA)
    assert name_matches("Maya Smith-Jones", Child("x", "1", "Maya", "Smith"))
    assert name_matches("José Núñez", Child("x", "1", "Jose", "Nunez"))
    assert not name_matches("Maya Jones", MAYA)
