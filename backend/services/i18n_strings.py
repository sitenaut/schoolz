"""Deterministic Spanish and Chinese for the text the backend itself authors (day labels,
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
    "zh": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
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
    },
    "zh": {
        "Main office": "学校办公室",
        "Nurse": "校医",
        "Counselor": "辅导员",
        "Principal": "校长",
        "Assistant principal": "副校长",
        "SACC": "课后托管（SACC）",
        "Social worker": "社工",
    },
}

_DAY_LABELS = {"es": {"Tomorrow": "Mañana"}, "zh": {"Tomorrow": "明天"}}

# The closure boilerplate a Spanish rendering of "SCHOOLS CLOSED - Labor Day"
# starts with; stripped the same way school_today.classify_day strips the
# English, since the status pill already says "Cerrado".
_ES_CLOSED_PREFIX_RE = re.compile(
    r"^\s*(las\s+)?(escuelas?|distrito(\s+escolar)?)\s+(cerrad[oa]s?|cierran?)\s*[-:–]?\s*"
    r"|^\s*no\s+hay\s+clases\s*[-:–]?\s*",
    re.I,
)

_ZH_CLOSED_PREFIX_RE = re.compile(
    r"^\s*(全?(学校|学区))\s*(全部)?\s*(关闭|停课|放假|休息)\s*[-:：–—]?\s*"
    r"|^\s*(停课|不上课|无课)\s*[-:：–—]?\s*"
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
    return {"es": f"Día {number}", "zh": f"第{number}天"}.get(lang, f"Day {number}")


def rotation_title(title: str, lang: str) -> str | None:
    """A rotation-feed title ("Day 3", "Day 3 ( 3, 4, 1, LL)") in `lang`, or
    None if it isn't one. These are the bulk of a district calendar and need
    no model."""
    if not is_localized(lang):
        return None
    m = _ROTATION_RE.match(title)
    if not m:
        return None
    return rotation_label(m.group(1), lang) + (f" {m.group(2)}" if m.group(2) else "")


def early_dismissal_label(lang: str) -> str:
    return {"es": "Salida temprana", "zh": "提前放学"}.get(lang, "Early dismissal")


def hours_phrase(kind: str, time_text: str, lang: str) -> str:
    """kind: "opens" (delayed opening with no end time) | "out" (early
    dismissal with no start time)."""
    if lang == "es":
        return f"Abre {time_text}" if kind == "opens" else f"Salida {time_text}"
    if lang == "zh":
        return f"{time_text} 开门" if kind == "opens" else f"{time_text} 放学"
    return f"Opens {time_text}" if kind == "opens" else f"Out {time_text}"


def strip_closed_prefix(translated_title: str, lang: str = "es") -> str | None:
    """The reason part of a translated "SCHOOLS CLOSED - X" title, or the
    whole title when it isn't shaped that way (never empty)."""
    pattern = _ZH_CLOSED_PREFIX_RE if lang == "zh" else _ES_CLOSED_PREFIX_RE
    stripped = pattern.sub("", translated_title).strip()
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


# --- Chinese: no gender/number agreement, so a much smaller table ----------

_SKY_ZH = {
    "sunny": "晴",
    "mostly sunny": "大部分晴",
    "partly sunny": "晴间多云",
    "clear": "晴朗",
    "mostly clear": "基本晴朗",
    "partly cloudy": "局部多云",
    "mostly cloudy": "大部分多云",
    "cloudy": "多云",
    "overcast": "阴",
    "fog": "有雾",
    "patchy fog": "局部有雾",
    "haze": "霾",
    "windy": "大风",
    "breezy": "有微风",
    "hot": "炎热",
}

_PRECIP_ZH = {
    "rain": "雨",
    "rain showers": "阵雨",
    "showers": "阵雨",
    "thunderstorms": "雷暴",
    "drizzle": "毛毛雨",
    "snow": "雪",
    "snow showers": "阵雪",
    "snow flurries": "小雪",
    "flurries": "小雪",
    "sleet": "雨夹雪",
    "freezing rain": "冻雨",
    "wintry mix": "雨雪混合",
}


def _precip_nouns_zh(low: str) -> str | None:
    parts = [p.strip() for p in low.split(" and ")]
    if not all(p in _PRECIP_ZH for p in parts):
        return None
    return "和".join(_PRECIP_ZH[p] for p in parts)


def _precip_phrase_zh(text: str) -> str | None:
    low = text.strip().lower()
    for qual, zh in (("slight chance", "小概率有"), ("chance", "可能有")):
        if low.startswith(qual + " "):
            nouns = _precip_nouns_zh(low[len(qual) + 1 :])
            return f"{zh}{nouns}" if nouns else None
    if low.endswith(" likely"):
        nouns = _precip_nouns_zh(low[: -len(" likely")])
        return f"很可能有{nouns}" if nouns else None
    first, _, rest = low.partition(" ")
    adj = {"scattered": "零星", "isolated": "局部"}.get(first)
    if adj and rest:
        nouns = _precip_nouns_zh(rest)
        return f"{adj}{nouns}" if nouns else None
    return _precip_nouns_zh(low)


def condition_zh(english: str) -> str:
    """As condition_es: every piece recognised, or the English comes back whole."""
    out = []
    for piece in re.split(r"\s+then\s+", english.strip(), flags=re.I):
        phrase = _SKY_ZH.get(piece.strip().lower()) or _precip_phrase_zh(piece)
        if not phrase:
            return english
        out.append(phrase)
    return "，随后".join(out)


def localize_weather(weather: dict, lang: str) -> dict:
    """The weather dict from services/weather.summarize, in `lang`. Only the
    free-text `condition` is translated. The day/drop-off/pickup labels
    ("Today", "Now", "Morning", "Afternoon", clock times) stay English on
    purpose: the frontend compares them and translates them itself. Numbers
    and the `items` codes are language-neutral."""
    if lang == "es":
        return {**weather, "condition": condition_es(weather["condition"])}
    if lang == "zh":
        return {**weather, "condition": condition_zh(weather["condition"])}
    return weather
