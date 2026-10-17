"""Everyday words for a category, so a search in plain words finds listings
that use the official ones.

Search matches the typed text inside a listing's own wording, and NJ 211
writes "ESL" or "Adult Basic Education", never "English classes" - so
"English classes", "learn English" or "clases de inglés" found nothing.
A query containing one of these phrases also matches the whole category.
Phrases are compared lowercased with accents removed, in every language
Localz is offered in.
"""
from __future__ import annotations

import unicodedata

# category -> phrases. A phrase matches anywhere in the query, except the
# ones in EXACT, which would be too broad inside a longer query ("English
# speaking doctor" is not a request for classes).
PHRASES: dict[str, tuple[str, ...]] = {
    "english": (
        "english class", "english classes", "english lesson", "english lessons", "english course",
        "english courses", "learn english", "learning english",
        "esl", "esol", "english as a second language",
        "clases de ingles", "clase de ingles", "aprender ingles", "ingles",  # es
        "英语", "英文", "学英语",  # zh
        "영어",  # ko
        "अंग्रेज",  # hi (अंग्रेज़ी / अंग्रेजी)
    ),
}
EXACT: dict[str, tuple[str, ...]] = {"english": ("english",)}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    # Drop Latin accents only: Hindi's vowel signs and nukta are combining
    # marks too, and removing them would change the word.
    return "".join(c for c in decomposed if not (unicodedata.combining(c) and ord(c) < 0x0370)).strip()


def _word_in(phrase: str, query: str) -> bool:
    """Whole-word match for Latin phrases ("esl" must not match "tesla");
    substring for scripts without spaces between words."""
    if not phrase.isascii():
        return phrase in query
    padded = f" {''.join(c if c.isalnum() else ' ' for c in query)} "
    return f" {phrase} " in padded


def categories_meant(query: str) -> list[str]:
    """The categories a search in everyday words is asking for."""
    q = _fold(query)
    if not q:
        return []
    return [
        category
        for category, phrases in PHRASES.items()
        if q in EXACT.get(category, ()) or any(_word_in(_fold(p), q) for p in phrases)
    ]
