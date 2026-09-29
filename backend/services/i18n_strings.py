"""Deterministic Spanish for the text the backend itself authors (day labels,
weather, contact roles). English is the source and stays in the code as-is;
every function here is English in, `lang`-appropriate out, and returns its
input untouched for "en" or for anything it doesn't recognise - an English
word beside Spanish ones beats a wrong translation. No model calls: these
strings are a closed set, and they must work with no API key.

School-authored content (newsletter items) is a different problem, solved
by services/content_translation.py."""

import re

_WEEKDAYS = {
    "es": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
}

_CONTACT_ROLE_LABELS = {
    "es": {
        "Main office": "Oficina principal",
        "Nurse": "Enfermería",
        "Counselor": "Consejería",
        "Principal": "Director(a)",
        "Assistant principal": "Subdirector(a)",
        "SACC": "SACC",
        "Social worker": "Trabajador(a) social",
    }
}

_DAY_LABELS = {"es": {"Tomorrow": "Mañana"}}

# The closure boilerplate a Spanish rendering of "SCHOOLS CLOSED - Labor Day"
# starts with; stripped the same way school_today.classify_day strips the
# English, since the status pill already says "Cerrado".
_ES_CLOSED_PREFIX_RE = re.compile(
    r"^\s*(las\s+)?(escuelas?|distrito(\s+escolar)?)\s+(cerrad[oa]s?|cierran?)\s*[-:–]?\s*"
    r"|^\s*no\s+hay\s+clases\s*[-:–]?\s*",
    re.I,
)

_ROTATION_RE = re.compile(r"^\s*Day\s+(\d+)\s*(\([^)]*\))?\s*$", re.I)


def is_localized(lang: str) -> bool:
    return lang in _WEEKDAYS


def weekday_abbr(index: int, english: str, lang: str) -> str:
    return _WEEKDAYS[lang][index] if is_localized(lang) else english


def day_label(label: str, weekday_index: int, lang: str) -> str:
    """"Tomorrow" or a weekday abbreviation ("Mon"), as school_today builds it."""
    if not is_localized(lang):
        return label
    return _DAY_LABELS[lang].get(label) or _WEEKDAYS[lang][weekday_index]


def contact_label(label: str, lang: str) -> str:
    return _CONTACT_ROLE_LABELS.get(lang, {}).get(label, label)


def rotation_label(number: str, lang: str) -> str:
    return f"Día {number}" if lang == "es" else f"Day {number}"


def rotation_title(title: str, lang: str) -> str | None:
    """A rotation-feed title ("Day 3", "Day 3 ( 3, 4, 1, LL)") in `lang`, or
    None if it isn't one. These are the bulk of a district calendar and need
    no model."""
    if lang != "es":
        return None
    m = _ROTATION_RE.match(title)
    if not m:
        return None
    return f"Día {m.group(1)}" + (f" {m.group(2)}" if m.group(2) else "")


def early_dismissal_label(lang: str) -> str:
    return "Salida temprana" if lang == "es" else "Early dismissal"


def hours_phrase(kind: str, time_text: str, lang: str) -> str:
    """kind: "opens" (delayed opening with no end time) | "out" (early
    dismissal with no start time)."""
    if lang == "es":
        return f"Abre {time_text}" if kind == "opens" else f"Salida {time_text}"
    return f"Opens {time_text}" if kind == "opens" else f"Out {time_text}"


def strip_closed_prefix(translated_title: str) -> str | None:
    """The reason part of a translated "SCHOOLS CLOSED - X" title, or the
    whole title when it isn't shaped that way (never empty)."""
    stripped = _ES_CLOSED_PREFIX_RE.sub("", translated_title).strip()
    return stripped or None


# --- NWS forecast phrases ---------------------------------------------------

_SKY = {
    "sunny": "Soleado",
    "mostly sunny": "Mayormente soleado",
    "partly sunny": "Parcialmente soleado",
    "clear": "Despejado",
    "mostly clear": "Mayormente despejado",
    "partly cloudy": "Parcialmente nublado",
    "mostly cloudy": "Mayormente nublado",
    "cloudy": "Nublado",
    "overcast": "Cubierto",
    "fog": "Niebla",
    "patchy fog": "Niebla en algunas zonas",
    "haze": "Bruma",
    "windy": "Ventoso",
    "breezy": "Con brisa",
    "hot": "Caluroso",
}

# noun -> (Spanish, feminine, plural)
_PRECIP = {
    "rain": ("lluvia", True, False),
    "rain showers": ("chubascos", False, True),
    "showers": ("chubascos", False, True),
    "thunderstorms": ("tormentas eléctricas", True, True),
    "drizzle": ("llovizna", True, False),
    "snow": ("nieve", True, False),
    "snow showers": ("nevadas", True, True),
    "snow flurries": ("ráfagas de nieve", True, True),
    "flurries": ("ráfagas de nieve", True, True),
    "sleet": ("aguanieve", True, False),
    "freezing rain": ("lluvia helada", True, False),
    "wintry mix": ("mezcla invernal", True, False),
}

_ADJ = {"scattered": "dispers", "isolated": "aislad", "likely": "probable"}
_QUALIFIERS = {"slight chance": "Leve probabilidad de", "chance": "Probabilidad de"}


def _agree(stem: str, feminine: bool, plural: bool) -> str:
    if stem == "probable":
        return "probables" if plural else "probable"
    return stem + ("a" if feminine else "o") + ("s" if plural else "")


def _precip_phrase(text: str) -> str | None:
    low = text.strip().lower()
    for qual, es in _QUALIFIERS.items():
        if low.startswith(qual + " "):
            nouns = _precip_nouns(low[len(qual) + 1 :])
            return f"{es} {nouns}" if nouns else None
    if low.endswith(" likely"):
        base = low[: -len(" likely")]
        nouns = _precip_nouns(base)
        if not nouns:
            return None
        head = _PRECIP[base.split(" and ")[0].strip()]
        return f"{nouns.capitalize()} {_agree('probable', head[1], head[2])}"
    first, _, rest = low.partition(" ")
    if first in _ADJ and rest:
        nouns = _precip_nouns(rest)
        if not nouns:
            return None
        head = _PRECIP[rest.split(" and ")[0].strip()]
        return f"{nouns.capitalize()} {_agree(_ADJ[first], head[1], head[2])}"
    nouns = _precip_nouns(low)
    return nouns.capitalize() if nouns else None


def _precip_nouns(low: str) -> str | None:
    parts = [p.strip() for p in low.split(" and ")]
    if not all(p in _PRECIP for p in parts):
        return None
    return " y ".join(_PRECIP[p][0] for p in parts)


def condition_es(english: str) -> str:
    """An NWS shortForecast ("Chance Rain Showers then Mostly Cloudy") in
    Spanish. Every piece must be recognised or the English is returned whole -
    a half-translated forecast is worse than an English one."""
    pieces = re.split(r"\s+then\s+", english.strip(), flags=re.I)
    out = []
    for piece in pieces:
        key = piece.strip().lower()
        phrase = _SKY.get(key) or _precip_phrase(piece)
        if not phrase:
            return english
        out.append(phrase)
    return " luego ".join(out) if len(out) > 1 else out[0]


def localize_weather(weather: dict, lang: str) -> dict:
    """The weather dict from services/weather.summarize, in `lang`. Only the
    free-text `condition` is translated. The day/drop-off/pickup labels
    ("Today", "Now", "Morning", "Afternoon", clock times) stay English on
    purpose: the frontend compares them and translates them itself. Numbers
    and the `items` codes are language-neutral."""
    if lang != "es":
        return weather
    return {**weather, "condition": condition_es(weather["condition"])}
