import pytest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from services.weather import LOCAL_TZ, school_window, summarize, zip_from_address

_DAY = date(2026, 10, 14)


def _school(**kw):
    base = dict(start_time="7:30 AM", end_time="2:30 PM", early_dismissal_time="11:45 AM", delayed_opening_time="9:30 AM")
    base.update(kw)
    return SimpleNamespace(**base)


def _hours(temps, pops=None, forecast="Sunny", start_hour=6):
    pops = pops or [0] * len(temps)
    return [
        {"start": datetime(2026, 10, 14, start_hour + i, tzinfo=LOCAL_TZ), "temp": t, "pop": p, "forecast": f if isinstance(f := forecast, str) else forecast[i]}
        for i, (t, p) in enumerate(zip(temps, pops))
    ]


def test_window_runs_half_hour_before_bell_to_hour_after_dismissal():
    start, bell, dismissal, end = school_window(_school(), "open", _DAY)
    assert (start.hour, start.minute) == (7, 0)
    assert (bell.hour, bell.minute) == (7, 30)
    assert (dismissal.hour, dismissal.minute) == (14, 30)
    assert (end.hour, end.minute) == (15, 30)


def test_window_follows_early_dismissal_and_delayed_opening():
    _, _, dismissal, _ = school_window(_school(), "early_dismissal", _DAY)
    assert (dismissal.hour, dismissal.minute) == (11, 45)
    _, bell, _, _ = school_window(_school(), "delayed", _DAY)
    assert (bell.hour, bell.minute) == (9, 30)


def test_window_falls_back_when_the_school_has_no_hours():
    start, bell, dismissal, end = school_window(_school(start_time=None, end_time=None), "open", _DAY)
    assert (bell.hour, dismissal.hour) == (8, 15)


def test_cold_morning_warm_afternoon_still_says_coat():
    # The case a daily high hides: 44 at the bus stop, 68 by pickup.
    periods = _hours([44, 46, 50, 55, 60, 64, 67, 68, 68, 66, 63])
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert out["low"] == 46 and out["high"] == 68  # 6 AM is outside the 7:00 window
    assert "coat" in out["items"]


def test_mild_day_with_a_big_swing_suggests_layers():
    periods = _hours([62, 63, 66, 70, 74, 77, 79, 80, 80, 78, 76])
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert out["items"] == ["layers"]


def test_rain_needs_both_a_real_chance_and_rain_wording():
    forecast = ["Mostly Cloudy"] * 8 + ["Chance Rain Showers"] * 3
    periods = _hours([65] * 11, pops=[10] * 8 + [60, 70, 70], forecast=forecast)
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert "umbrella" in out["items"]
    assert out["rain_from"] == "2 PM"
    assert out["rain_chance"] == 70

    # A high chance of "Mostly Cloudy" is not a reason to pack an umbrella.
    dry = _hours([65] * 11, pops=[50] * 11, forecast="Mostly Cloudy")
    assert "umbrella" not in summarize(dry, None, school_window(_school(), "open", _DAY))["items"]


def test_freezing_snow_day():
    periods = _hours([24, 25, 27, 29, 30, 31, 31, 30, 29, 28, 27], pops=[60] * 11, forecast="Snow Likely")
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert out["items"][:2] == ["heavy_coat", "hat_gloves"]
    assert "boots" in out["items"]
    assert "umbrella" not in out["items"]


def test_uv_drives_sunscreen_only_inside_the_window():
    periods = _hours([75] * 11)
    uv = {datetime(2026, 10, 14, h, tzinfo=LOCAL_TZ): v for h, v in [(8, 2), (11, 7), (13, 8), (17, 10)]}
    out = summarize(periods, uv, school_window(_school(), "open", _DAY))
    assert out["uv_max"] == 8  # the 5 PM reading is after the window closes
    assert "sunscreen" in out["items"] and "sun_hat" in out["items"]


def test_no_uv_data_never_guesses_sunscreen():
    out = summarize(_hours([80] * 11), None, school_window(_school(), "open", _DAY))
    assert "sunscreen" not in out["items"]


def test_dropoff_and_pickup_temps_come_from_their_own_hours():
    periods = _hours([40, 42, 45, 50, 55, 58, 60, 62, 64, 63, 60])
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert out["dropoff_temp"] == 42  # the 7 AM hour holds 7:30
    assert out["pickup_temp"] == 64  # the 2 PM hour holds 2:30
    assert out["dropoff_label"] == "7:30 AM" and out["pickup_label"] == "2:30 PM"


def test_a_passed_dropoff_shows_the_current_hour_as_now_not_a_dash():
    # NWS hourly starts at the current hour, so by 9 AM the 7:30 bell is gone.
    periods = _hours([55, 58, 60, 62, 64, 63, 60], start_hour=9)
    out = summarize(periods, None, school_window(_school(), "open", _DAY))
    assert (out["dropoff_temp"], out["dropoff_label"]) == (55, "Now")
    assert out["pickup_temp"] == 63 and out["pickup_label"] == "2:30 PM"


def test_forecast_that_does_not_cover_the_window_is_none():
    tomorrow = [dict(p, start=p["start"] + timedelta(days=1)) for p in _hours([60] * 11)]
    assert summarize(tomorrow, None, school_window(_school(), "open", _DAY)) is None


def test_zip_is_the_last_five_digit_group():
    assert zip_from_address("1750 Kresson Road, Cherry Hill, NJ 08003") == "08003"
    assert zip_from_address("12345 Main St, Voorhees, NJ 08043-1234") == "08043"
    assert zip_from_address(None) is None


def test_default_hours_are_labeled_as_such_not_as_real_bell_times():
    school = _school(start_time=None, end_time=None)
    out = summarize(_hours([60] * 11), None, school_window(school, "open", _DAY), known_hours=(False, False))
    assert (out["dropoff_label"], out["pickup_label"]) == ("Morning", "Afternoon")


def _pick(status, now_hour, now_minute=0, next_status="open"):
    from services.weather import pick_weather_day
    now = datetime(2026, 10, 14, now_hour, now_minute, tzinfo=LOCAL_TZ)
    return pick_weather_day(_school(), _DAY, status, date(2026, 10, 15), next_status, now)


def test_school_morning_and_afternoon_show_today():
    assert _pick("open", 6) == (_DAY, "open", True)
    assert _pick("open", 15, 29) == (_DAY, "open", True)  # still inside the hour after 2:30 dismissal


def test_after_the_window_closes_it_is_tomorrows_weather():
    assert _pick("open", 15, 30) == (date(2026, 10, 15), "open", False)
    assert _pick("open", 21) == (date(2026, 10, 15), "open", False)


def test_an_early_dismissal_day_hands_off_earlier():
    # Out at 11:45, so by 1 PM the day is over.
    assert _pick("early_dismissal", 13)[2] is False


def test_no_school_today_shows_the_next_school_day_all_day():
    assert _pick("weekend", 8) == (date(2026, 10, 15), "open", False)
    assert _pick("closed", 8, next_status="delayed") == (date(2026, 10, 15), "delayed", False)


@pytest.mark.anyio
async def test_today_endpoint_takes_a_date_and_says_which_day_the_forecast_is_for(monkeypatch):
    import os
    import uuid
    from datetime import timedelta

    os.environ.setdefault("JWT_SECRET", "test-secret")
    os.environ.setdefault("AUTH_MODE", "local")
    from httpx import ASGITransport, AsyncClient

    import database
    from main import app
    from models import School
    from services import school_today

    async def fake_weather(school, status, day, lang="en"):
        return {
            "dropoff_label": "8:00 AM", "dropoff_temp": 55, "pickup_label": "3:00 PM", "pickup_temp": 70,
            "low": 55, "high": 70, "rain_chance": 0, "rain_from": None, "condition": "Sunny", "uv_max": None, "items": ["jacket"],
        }

    monkeypatch.setattr(school_today, "today_weather", fake_weather)
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        db.add(School(name=f"Weather On {run}", slug=f"weather-on-{run}", school_type="elementary"))
        await db.commit()

    # Pick a weekday a few days out so it is a plain school day with no calendar items.
    day = datetime.now(LOCAL_TZ).date() + timedelta(days=3)
    while day.weekday() >= 5:
        day += timedelta(days=1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"/schools/weather-on-{run}/today", params={"on": day.isoformat()})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["date"] == day.isoformat()
        assert body["weather"]["date"] == day.isoformat()

        far = day + timedelta(days=30)
        assert (await client.get(f"/schools/weather-on-{run}/today", params={"on": far.isoformat()})).status_code == 422
        assert (await client.get(f"/schools/weather-on-{run}/today", params={"on": "tomorrow"})).status_code == 422
