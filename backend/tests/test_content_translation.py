import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app
from models import ContentTranslation, District, School, SchoolContentItem
from services import content_translation as ct
from services import i18n_strings, weather
from services.school_today import LOCAL_TZ, build_today

ES = {"X-Schoolz-Lang": "es"}
FUTURE = datetime.now(timezone.utc) + timedelta(days=3)


@pytest.fixture(autouse=True)
def _reset_translation_state():
    ct._cooldown_until = 0.0
    ct._INFLIGHT.clear()
    yield
    ct._cooldown_until = 0.0
    ct._INFLIGHT.clear()


def _fake_model(calls: list):
    async def fake(payload, lang):
        calls.append([row["title"] for row in payload])
        return {row["n"]: ("ES: " + row["title"], ("ES: " + row["description"]) if row.get("description") else None) for row in payload}

    return fake


async def _school_with_item(title="Picture Day", description="Bring the form.", **item_kw):
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Trans School {run}", slug=f"trans-{run}", school_type="elementary")
        db.add(school)
        await db.flush()
        item = SchoolContentItem(
            scope="school", school_id=school.id, category="event", title=title, description=description,
            start_date=FUTURE, is_all_day=True, is_current=True, **item_kw,
        )
        db.add(item)
        await db.commit()
        return school.slug, school.id, item.id


async def _content(client, slug, headers=None):
    res = await client.get(f"/schools/{slug}/content", headers=headers or {})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.anyio
async def test_english_is_untouched_and_never_calls_the_model(monkeypatch):
    async def boom(payload, lang):
        raise AssertionError("English must not reach the model")

    monkeypatch.setattr(ct, "_call_model", boom)
    slug, _, _ = await _school_with_item()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug)
        assert (row["title"], row["translated"], row["title_original"]) == ("Picture Day", False, None)
        [row] = await _content(client, slug, {"X-Schoolz-Lang": "en"})
        assert row["title"] == "Picture Day"


@pytest.mark.anyio
async def test_spanish_translates_once_stores_it_and_serves_it_to_the_next_visitor(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ct, "_call_model", _fake_model(calls))
    slug, _, item_id = await _school_with_item()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug, ES)
        assert row["title"] == "ES: Picture Day"
        assert row["description"] == "ES: Bring the form."
        assert row["translated"] is True
        assert (row["title_original"], row["description_original"]) == ("Picture Day", "Bring the form.")
        assert row["category"] == "event" and row["start_date"]  # dates/categories untouched

        [row] = await _content(client, slug, ES)
        assert row["title"] == "ES: Picture Day"
        assert len(calls) == 1  # second visitor read the stored row

        # English is still English on the same item.
        [row] = await _content(client, slug)
        assert row["title"] == "Picture Day" and row["translated"] is False

    async with database.SessionLocal() as db:
        [stored] = (await db.execute(select(ContentTranslation).where(ContentTranslation.item_id == item_id))).scalars().all()
        assert (stored.lang, stored.title, stored.source_hash) == ("es", "ES: Picture Day", ct.source_hash("Picture Day", "Bring the form."))


@pytest.mark.anyio
async def test_stored_translation_is_served_without_a_model_call(monkeypatch):
    async def boom(payload, lang):
        raise AssertionError("fresh stored translation must not be re-made")

    monkeypatch.setattr(ct, "_call_model", boom)
    slug, _, item_id = await _school_with_item()
    async with database.SessionLocal() as db:
        db.add(ContentTranslation(item_id=item_id, lang="es", title="Día de fotos", description="Traiga el formulario.", source_hash=ct.source_hash("Picture Day", "Bring the form."), model="test"))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug, ES)
        assert (row["title"], row["description"], row["translated"]) == ("Día de fotos", "Traiga el formulario.", True)


@pytest.mark.anyio
async def test_edited_item_has_a_stale_hash_and_is_retranslated(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ct, "_call_model", _fake_model(calls))
    slug, _, item_id = await _school_with_item()
    async with database.SessionLocal() as db:
        db.add(ContentTranslation(item_id=item_id, lang="es", title="Día de fotos", description="Traiga el formulario.", source_hash=ct.source_hash("Picture Day", "OLD description"), model="test"))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug, ES)
        assert row["title"] == "ES: Picture Day"
        assert calls == [["Picture Day"]]
    async with database.SessionLocal() as db:
        [stored] = (await db.execute(select(ContentTranslation).where(ContentTranslation.item_id == item_id))).scalars().all()
        assert stored.source_hash == ct.source_hash("Picture Day", "Bring the form.")  # updated in place, still one row


@pytest.mark.anyio
async def test_model_failure_serves_english_and_backs_off(monkeypatch):
    attempts = []

    async def failing(payload, lang):
        attempts.append(1)
        raise RuntimeError("anthropic is down")

    monkeypatch.setattr(ct, "_call_model", failing)
    slug, _, _ = await _school_with_item()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug, ES)
        assert (row["title"], row["description"], row["translated"], row["title_original"]) == ("Picture Day", "Bring the form.", False, None)
        await _content(client, slug, ES)
        assert len(attempts) == 1  # cooldown: an outage isn't retried on every page load


@pytest.mark.anyio
async def test_missing_api_key_degrades_to_english(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    slug, _, _ = await _school_with_item()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        [row] = await _content(client, slug, ES)
        assert (row["title"], row["translated"]) == ("Picture Day", False)


@pytest.mark.anyio
async def test_model_that_skips_an_item_leaves_only_that_one_in_english(monkeypatch):
    async def partial(payload, lang):
        return {row["n"]: ("ES: " + row["title"], None) for row in payload if row["title"] != "Skipped"}

    monkeypatch.setattr(ct, "_call_model", partial)
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Partial {run}", slug=f"partial-{run}", school_type="elementary")
        db.add(school)
        await db.flush()
        for n, title in enumerate(["Kept", "Skipped"]):
            db.add(SchoolContentItem(scope="school", school_id=school.id, category="event", title=title, start_date=FUTURE + timedelta(hours=n), is_all_day=False, is_current=True))
        await db.commit()
        slug = school.slug
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rows = {r["title_original"] or r["title"]: r for r in await _content(client, slug, ES)}
        assert rows["Kept"]["title"] == "ES: Kept" and rows["Kept"]["translated"] is True
        assert rows["Skipped"]["title"] == "Skipped" and rows["Skipped"]["translated"] is False


@pytest.mark.anyio
async def test_calendar_search_matches_the_stored_translation_only_in_spanish(monkeypatch):
    async def fake(payload, lang):
        return {row["n"]: ("Feria del Libro", None) for row in payload}

    monkeypatch.setattr(ct, "_call_model", fake)
    slug, school_id, _item_id = await _school_with_item(title="Book Fair", description=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/calendar", params={"school_id": school_id}, headers=ES)).status_code == 200  # stores it
        es = await client.get("/calendar", params={"school_id": school_id, "q": "feria"}, headers=ES)
        assert [r["title_original"] for r in es.json()] == ["Book Fair"]
        en = await client.get("/calendar", params={"school_id": school_id, "q": "feria"})
        assert en.json() == []


@pytest.mark.anyio
async def test_calendar_translates_and_rotation_titles_are_deterministic(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ct, "_call_model", _fake_model(calls))
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Cal District {run}")
        db.add(district)
        await db.flush()
        school = School(name=f"Cal School {run}", slug=f"cal-{run}", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.flush()
        db.add(SchoolContentItem(scope="school", school_id=school.id, category="event", title="Book Fair", start_date=FUTURE, is_all_day=True, is_current=True))
        db.add(SchoolContentItem(scope="district", district_id=district.id, category="event", title="Day 3 ( 3, 4, 1, LL)", start_date=FUTURE, is_all_day=True, is_current=True, source="ics_feed"))
        await db.commit()
        school_id = school.id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/calendar", params={"school_id": school_id}, headers=ES)
        assert res.status_code == 200
        by_orig = {(r["title_original"] or r["title"]): r for r in res.json()}
        assert by_orig["Book Fair"]["title"] == "ES: Book Fair" and by_orig["Book Fair"]["translated"] is True
        rotation = by_orig["Día 3 ( 3, 4, 1, LL)"]  # deterministic: no title_original
        assert rotation["translated"] is False and rotation["title_original"] is None
        assert calls == [["Book Fair"]]  # the rotation marker never reached the model


@pytest.mark.anyio
async def test_today_in_spanish_uses_translated_closure_reason_and_spanish_labels(monkeypatch):
    calls: list = []

    async def fake(payload, lang):
        calls.append(payload)
        table = {"SCHOOLS CLOSED - Fall Recess": "ESCUELAS CERRADAS - Receso de otoño", "Back to School Night": "Noche de regreso a clases"}
        return {row["n"]: (table[row["title"]], None) for row in payload}

    monkeypatch.setattr(ct, "_call_model", fake)
    run = uuid.uuid4().hex[:8]
    today = date(2026, 10, 14)  # Wednesday
    async with database.SessionLocal() as db:
        school = School(name=f"Today ES {run}", slug=f"today-es-{run}", school_type="elementary")
        db.add(school)
        await db.flush()
        at = lambda d: datetime.combine(d, datetime.min.time(), LOCAL_TZ)
        db.add(SchoolContentItem(scope="school", school_id=school.id, category="event", title="SCHOOLS CLOSED - Fall Recess", start_date=at(date(2026, 10, 15)), is_all_day=True, is_current=True))
        db.add(SchoolContentItem(scope="school", school_id=school.id, category="event", title="Back to School Night", start_date=at(date(2026, 10, 16)), is_all_day=True, is_current=True))
        db.add(SchoolContentItem(scope="school", school_id=school.id, category="event", title="Day 4", start_date=at(today), is_all_day=True, is_current=True))
        await db.commit()

        es = await build_today(db, school, today, lang="es")
        en = await build_today(db, school, today)

    assert [d.weekday for d in es.week] == ["Lun", "Mar", "Mié", "Jue", "Vie"]
    assert [d.weekday for d in en.week] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    thu = es.week[3]
    assert (thu.status, thu.status_label) == ("closed", "Receso de otoño")
    assert en.week[3].status_label == "Fall Recess"
    assert es.rotation_day == "Día 4" and en.rotation_day == "Day 4"
    assert [a.title for a in es.alerts] == ["ESCUELAS CERRADAS - Receso de otoño"]
    night = next(i for i in es.upcoming if i.title_original == "Back to School Night")
    assert night.title == "Noche de regreso a clases" and night.translated
    en_night = next(i for i in en.upcoming if i.title == "Back to School Night")
    assert not en_night.translated
    assert es.date == en.date == "2026-10-14"  # shape and dates identical
    assert len(calls) == 1  # one model call covers the closure, alert and upcoming items


@pytest.mark.anyio
async def test_today_hours_and_early_dismissal_labels_in_spanish():
    async with database.SessionLocal() as db:
        school = School(name="x", slug="x", school_type="elementary", early_dismissal_time="12:30 PM")
        from services.school_today import _hours

        assert _hours(school, "early_dismissal", "es") == "Salida 12:30 PM"
        assert _hours(school, "early_dismissal") == "Out 12:30 PM"
    assert i18n_strings.early_dismissal_label("es") == "Salida temprana"


@pytest.mark.anyio
async def test_weather_condition_is_spanish_but_labels_stay_english_for_the_frontend(monkeypatch):
    day = date(2026, 10, 14)
    periods = [
        {"start": datetime(2026, 10, 14, h, tzinfo=weather.LOCAL_TZ), "temp": 50, "pop": 60, "forecast": "Chance Rain Showers"}
        for h in range(6, 17)
    ]

    async def fake_forecast(grid):
        return periods

    monkeypatch.setattr(weather, "hourly_forecast", fake_forecast)
    school = SimpleNamespace(id="s", nws_grid="PHI/1,1", address=None, start_time="7:30 AM", end_time="2:30 PM", early_dismissal_time=None, delayed_opening_time=None)
    en = await weather.today_weather(school, "open", day)
    es = await weather.today_weather(school, "open", day, "es")
    assert en["condition"] == "Chance Rain Showers"
    assert es["condition"] == "Probabilidad de chubascos"
    for key in ("dropoff_label", "pickup_label", "items", "low", "high", "rain_chance", "rain_from"):
        assert es[key] == en[key]

    known_off = weather.summarize(periods, None, weather.school_window(school, "open", day), known_hours=(False, False))
    assert i18n_strings.localize_weather(known_off, "es")["dropoff_label"] == "Morning"


def test_condition_phrases_translate_or_fall_back_to_english_whole():
    es = i18n_strings.condition_es
    assert es("Mostly Sunny") == "Mayormente soleado"
    assert es("Partly Cloudy") == "Parcialmente nublado"
    assert es("Slight Chance Rain Showers") == "Leve probabilidad de chubascos"
    assert es("Rain Likely") == "Lluvia probable"
    assert es("Showers Likely") == "Chubascos probables"
    assert es("Rain Likely then Sunny Skies") == "Rain Likely then Sunny Skies"
    assert es("Scattered Showers") == "Chubascos dispersos"
    assert es("Chance Snow then Mostly Cloudy") == "Probabilidad de nieve luego Mayormente nublado"
    assert es("Frogs") == "Frogs"
    assert es("Mostly Sunny then Frogs") == "Mostly Sunny then Frogs"  # never half-translated


def test_closed_prefix_stripping_in_spanish():
    strip = i18n_strings.strip_closed_prefix
    assert strip("ESCUELAS CERRADAS - Receso de otoño") == "Receso de otoño"
    assert strip("Las escuelas cerradas: Día del Trabajo") == "Día del Trabajo"
    assert strip("No hay clases - Yom Kipur") == "Yom Kipur"
    assert strip("Escuelas cerradas") is None
    assert strip("Receso de otoño") == "Receso de otoño"


def test_fold_strips_accents_and_case():
    from services.i18n import fold

    assert fold("Reunión de Padres") == "reunion de padres"
    assert fold("ESPAÑOL") == "espanol"
    assert fold("Güero, José") == "guero, jose"


@pytest.mark.anyio
async def test_search_ignores_accents_in_both_directions():
    from datetime import datetime, timezone

    import database
    from models import LocalEvent

    slug, school_id, _ = await _school_with_item(title="Reunión de Padres", description="Salón de música")
    src = f"fold_{uuid.uuid4().hex[:8]}"
    async with database.SessionLocal() as db:
        db.add(LocalEvent(source=src, source_event_id="1", title="Festival del Niño", start_time=datetime(2031, 6, 7, 14, tzinfo=timezone.utc)))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for q in ("reunion", "REUNIÓN", "musica", "salon de"):
            res = await client.get("/calendar", params={"school_id": school_id, "q": q})
            assert [r["title"] for r in res.json()] == ["Reunión de Padres"], q
            res = await client.get(f"/schools/{slug}/content", params={"q": q})
            assert [r["title"] for r in res.json()] == ["Reunión de Padres"], q
        # An unaccented title is found by an accented query too.
        slug2, school_id2, _ = await _school_with_item(title="Science Night", description=None)
        res = await client.get("/calendar", params={"school_id": school_id2, "q": "scíence"})
        assert [r["title"] for r in res.json()] == ["Science Night"]
        assert (await client.get("/calendar", params={"school_id": school_id, "q": "xyz"})).json() == []

        from tests.test_kids_api import _auth, _register

        token = await _register(client, f"fold_{uuid.uuid4().hex[:8]}@example.com")
        res = await client.get("/local-events", params={"q": "nino", "source": src}, headers=_auth(token))
        assert [e["title"] for e in res.json()["items"]] == ["Festival del Niño"]
