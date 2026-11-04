"""0146's Camden Toys for Tots sign-up: it changes only a listing that still
carries NJ 211's 2025 text, keeps the next refresh from putting that back,
and names no person."""
import importlib.util
from pathlib import Path

from resources import nj211
from resources.portal import Submission

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
spec = importlib.util.spec_from_file_location("m0146", _VERSIONS / "0146_toys_for_tots_camden_signup.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

# What NJ 211 says on 2026-11-04 (its 2025 sign-up).
NJ211_TEXT = (
    "The Elks Lodge will hold registration on <b>October 18, 2025</b>, from 1:00 pm - 4:00 pm at 1818 Mt. "
    "Ephraim Ave, exclusively for families residing in Camden City. Only the first 150 people in line will "
    "be registered. Camden County families should contact the Clark Family Breast Cancer Organization at "
    "856-580-4943 for assistance."
)


def test_the_stale_mark_is_in_nj211s_text_as_stored():
    assert M.STALE_MARK in nj211.detail_fields({"applicationProcess": NJ211_TEXT})[M.FIELD]
    assert M.STALE_MARK not in M.SIGN_UP


def test_the_sign_up_names_no_person_and_only_the_organizations_line():
    for name in ("Mr.", "Ms.", "Mrs.", "Vance", "Angie", "Clark @"):
        assert name not in M.SIGN_UP
    # The named volunteers' own numbers stay on the campaign's site.
    for number in ("856-254-5088", "856-993-4531"):
        assert number not in M.SIGN_UP
    assert "856-317-1876" in M.SIGN_UP


def test_the_sign_up_fits_where_a_provider_could_type_it():
    limit = Submission.model_fields["how_to_apply"].metadata[0].max_length
    assert len(M.SIGN_UP) <= limit
