from services.staff_roles import classify_role


def test_chief_school_administrator_is_the_principal():
    # Merchantville's head of its single school carries this title.
    assert classify_role("Chief School Administrator") == "principal"


def test_assistant_principal_still_wins_and_plain_administrator_is_unclassified():
    assert classify_role("Assistant Principal") == "assistant_principal"
    assert classify_role("School Administrator") is None


def test_secretary_to_a_principal_is_the_secretary():
    from services.staff_roles import classify_role

    assert classify_role("Secretary to the Dir. of Curr./Nokomis Principal") == "secretary"
    assert classify_role("Administrative Assistant to the Principal") == "secretary"
    assert classify_role("Principal") == "principal"
    assert classify_role("Assistant Principal") == "assistant_principal"
