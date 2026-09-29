"""Request language for API responses.

English is the source language and the default. The frontend sends
`X-Schoolz-Lang: es` (or `zh`) only when the visitor is on that language's page - never the
browser's Accept-Language, which would translate an English page for anyone
whose browser happens to be set to another language.
"""

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

SUPPORTED_LANGS = ("en", "es", "zh")
DEFAULT_LANG = "en"
LANG_HEADER = "X-Schoolz-Lang"


def normalize_lang(value: str | None) -> str:
    base = (value or "").strip().lower().split("-")[0]
    return base if base in SUPPORTED_LANGS else DEFAULT_LANG


def request_lang(request: Request) -> str:
    """FastAPI dependency: `lang: str = Depends(request_lang)`."""
    return normalize_lang(request.headers.get(LANG_HEADER) or request.query_params.get("lang"))


# Accent-insensitive search. Spanish speakers routinely type "reunion" for
# "reunión" (and "espanol" for "español"), so both the query and the column
# are lower-cased and folded through the same table. Postgres translate()
# rather than the unaccent extension: no extension to enable on Supabase, and
# Python and SQL cannot disagree because they share this one table.
_ACCENTED = "áéíóúüñàèìòùâêîôûäëïöç"
_PLAIN = "aeiouunaeiouaeiouaeioc"
_FOLD = str.maketrans(_ACCENTED, _PLAIN)


def fold(text: str) -> str:
    return text.lower().translate(_FOLD)


def folded(column) -> ColumnElement:
    """SQL twin of fold(): `folded(Model.title).like(f"%{fold(q)}%")`."""
    return func.translate(func.lower(column), _ACCENTED, _PLAIN)
