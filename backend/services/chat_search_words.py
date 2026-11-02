"""How the chat's searches turn a visitor's loose words into what listings
say. People write "seniors" and "knitting groups"; listings say "Senior Chair
Yoga" and "Knit & Crochet". Prod searches match text inside a field, so the
plural alone found a third of the senior events ("seniors" 21, "senior" 62).
"""

# These words narrow nothing, so they're neither searched nor scored.
STOPWORDS = {
    "the", "and", "for", "are", "any", "what", "whats", "when", "where", "near", "nearby", "around", "local",
    "events", "event", "this", "that", "with", "there", "going", "happening",
    "activities", "activity", "things", "thing", "stuff", "fun", "engaging", "like", "something", "programs",
    "program", "services", "service", "help",
}
SYNONYMS = {
    "fall": ("autumn", "harvest"),
    "autumn": ("fall", "harvest"),
    "harvest": ("fall", "autumn"),
    "senior": ("older adult",),
    "older": ("senior",),
    "elderly": ("senior", "older adult"),
    "retiree": ("senior",),
    "knitting": ("knit", "crochet", "yarn", "stitch"),
    "knit": ("crochet", "yarn", "stitch"),
    "crochet": ("knit", "yarn", "stitch"),
    "computer": ("tech", "smartphone", "digital"),
    "technology": ("computer", "smartphone", "digital"),
    "tech": ("computer", "smartphone", "digital"),
    "coding": ("python", "computer"),
    "iphone": ("smartphone", "tech", "computer"),
    "ipad": ("tablet", "tech", "computer"),
    "smartphone": ("iphone", "tech", "computer"),
    "online": ("virtual", "zoom"),
    "virtual": ("online", "zoom"),
}
_NOT_PLURAL = {"news"}


def singular(word: str) -> str:
    """'seniors' -> 'senior', 'classes' -> 'class', 'libraries' -> 'library'."""
    if word in _NOT_PLURAL or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "ches", "shes", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def own_terms(word: str) -> tuple[str, ...]:
    """What to search for the word itself. Text matching means "senior" also
    finds "seniors", but "library" doesn't find "libraries"."""
    stem = singular(word)
    return (stem,) if word.startswith(stem) else (word, stem)


def search_terms(word: str) -> tuple[str, ...]:
    return (*own_terms(word), *SYNONYMS.get(singular(word), ()))
