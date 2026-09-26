"""
Exports your Garmin data to garmin_data.json, next to this script,
so the dashboard (index.html) can display it.

Run it from your garmin-mcp folder with:
    venv\\Scripts\\python.exe export_garmin_data.py

It reuses the login token saved earlier by test_login.py, so it
should not ask for your password again. If the token has expired,
set GARMIN_EMAIL and GARMIN_PASSWORD as environment variables first,
or just re-run test_login.py.

Add --debug to also dump the raw Garmin responses to
garmin_raw_debug.json, which is useful if any numbers on the
dashboard look wrong and we need to fix a field name.
"""

import os
import sys
import json
import time
from datetime import date, timedelta
from garminconnect import Garmin

# How many days of sleep/HRV history to pull for the trend charts.
# Each day costs one extra request per metric, so keep this modest.
TREND_DAYS = 7

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(HERE, "garmin_data.json")
DEBUG_FILE = os.path.join(HERE, "garmin_raw_debug.json")
TOKENS = os.path.expanduser("~/.garminconnect")
DEBUG = "--debug" in sys.argv


def log(msg):
    print(msg, flush=True)


def login():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    g = Garmin(email, password) if (email and password) else Garmin()
    g.login(TOKENS)
    return g


def safe(label, fn, default=None):
    """Call fn(), and if it fails, warn and return default instead of crashing."""
    try:
        result = fn()
        time.sleep(0.4)  # be gentle with Garmin's servers
        return result
    except Exception as e:
        log(f"  ! could not get {label}: {e}")
        return default


def pick(d, *paths, default=None):
    """Try several possible nested-key paths and return the first that works."""
    if not d:
        return default
    for path in paths:
        cur = d
        ok = True
        for key in path:
            if isinstance(cur, dict) and key in cur and cur[key] is not None:
                cur = cur[key]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def main():
    log("Logging in to Garmin...")
    g = login()
    log("Logged in. Pulling today's data...")

    today = date.today()
    today_s = today.isoformat()

    raw = {}
    raw["sleep"] = safe("sleep", lambda: g.get_sleep_data(today_s))
    raw["hrv"] = safe("hrv", lambda: g.get_hrv_data(today_s))
    raw["spo2"] = safe("spo2", lambda: g.get_spo2_data(today_s))
    raw["stress"] = safe("stress", lambda: g.get_stress_data(today_s))
    raw["battery"] = safe("body battery", lambda: g.get_body_battery(today_s, today_s))
    raw["readiness"] = safe("training readiness", lambda: g.get_training_readiness(today_s))
    raw["vo2max"] = safe("vo2 max", lambda: g.get_max_metrics(today_s))
    raw["activities"] = safe(
        "activities",
        lambda: g.get_activities_by_date((today - timedelta(days=30)).isoformat(), today_s),
        default=[],
    )

    # ---- Today's summary numbers ----
    sleep_dto = pick(raw["sleep"], ("dailySleepDTO",), default={}) or {}
    sleep_score = pick(
        sleep_dto,
        ("sleepScores", "overall", "value"),
        ("sleepScores", "overallScore"),
    )
    sleep_seconds = pick(sleep_dto, ("sleepTimeSeconds",))
    deep_seconds = pick(sleep_dto, ("deepSleepSeconds",))
    light_seconds = pick(sleep_dto, ("lightSleepSeconds",))
    rem_seconds = pick(sleep_dto, ("remSleepSeconds",))
    awake_seconds = pick(sleep_dto, ("awakeSleepSeconds",))

    hrv_summary = pick(raw["hrv"], ("hrvSummary",), default={}) or {}
    hrv_last_night = pick(hrv_summary, ("lastNightAvg",), ("weeklyAvg",))
    hrv_status = pick(hrv_summary, ("status",))

    spo2_avg = pick(raw["spo2"], ("averageSpO2",), ("avgSleepSpO2",))
    spo2_low = pick(raw["spo2"], ("lowestSpO2",), ("lowestSpO2Value",))

    stress_avg = pick(raw["stress"], ("avgStressLevel",))
    stress_current = pick(raw["stress"], ("currentStressLevel",))

    battery_list = raw["battery"] if isinstance(raw["battery"], list) else []
    battery_today = battery_list[0] if battery_list else {}
    battery_charged = pick(battery_today, ("charged",), ("chargedValue",))
    battery_drained = pick(battery_today, ("drained",), ("drainedValue",))
    battery_values = pick(battery_today, ("bodyBatteryValuesArray",), default=[]) or []
    battery_current = None
    if battery_values:
        last_point = battery_values[-1]
        if isinstance(last_point, list) and len(last_point) > 1:
            battery_current = last_point[1]

    readiness_list = raw["readiness"] if isinstance(raw["readiness"], list) else []
    readiness_today = readiness_list[0] if readiness_list else {}
    readiness_score = pick(readiness_today, ("score",))
    readiness_level = pick(readiness_today, ("level",))

    vo2_list = raw["vo2max"] if isinstance(raw["vo2max"], list) else ([raw["vo2max"]] if raw["vo2max"] else [])
    vo2_today = vo2_list[0] if vo2_list else {}
    vo2max_value = pick(
        vo2_today,
        ("generic", "vo2MaxPreciseValue"),
        ("generic", "vo2MaxValue"),
        ("vo2MaxPreciseValue",),
        ("vo2MaxValue",),
    )

    # ---- Trends over the last TREND_DAYS ----
    log(f"Pulling {TREND_DAYS}-day sleep and HRV trends (this takes a little while)...")
    sleep_trend = []
    hrv_trend = []
    for i in range(TREND_DAYS - 1, -1, -1):
        d = today - timedelta(days=i)
        ds = d.isoformat()

        sd = safe(f"sleep {ds}", lambda ds=ds: g.get_sleep_data(ds))
        dto = pick(sd, ("dailySleepDTO",), default={}) or {}
        score = pick(dto, ("sleepScores", "overall", "value"), ("sleepScores", "overallScore"))
        sleep_trend.append({"date": ds, "score": score})

        hd = safe(f"hrv {ds}", lambda ds=ds: g.get_hrv_data(ds))
        summary = pick(hd, ("hrvSummary",), default={}) or {}
        value = pick(summary, ("lastNightAvg",), ("weeklyAvg",))
        hrv_trend.append({"date": ds, "value": value})

    # ---- Activities (last 10) ----
    activities_out = []
    for a in (raw["activities"] or [])[:10]:
        activities_out.append({
            "name": a.get("activityName"),
            "type": pick(a, ("activityType", "typeKey"), default="activity"),
            "date": (a.get("startTimeLocal") or "")[:16],
            "duration_min": round((a.get("duration") or 0) / 60, 1),
            "distance_km": round((a.get("distance") or 0) / 1000, 2),
            "avg_hr": a.get("averageHR"),
            "calories": a.get("calories"),
            "training_effect": a.get("aerobicTrainingEffect"),
        })

    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M"),
        "today": {
            "sleep_score": sleep_score,
            "sleep_hours": round(sleep_seconds / 3600, 1) if sleep_seconds else None,
            "sleep_deep_min": round(deep_seconds / 60) if deep_seconds else None,
            "sleep_light_min": round(light_seconds / 60) if light_seconds else None,
            "sleep_rem_min": round(rem_seconds / 60) if rem_seconds else None,
            "sleep_awake_min": round(awake_seconds / 60) if awake_seconds else None,
            "hrv": hrv_last_night,
            "hrv_status": hrv_status,
            "spo2_avg": spo2_avg,
            "spo2_low": spo2_low,
            "stress_avg": stress_avg,
            "stress_current": stress_current,
            "body_battery_current": battery_current,
            "body_battery_charged": battery_charged,
            "body_battery_drained": battery_drained,
            "readiness_score": readiness_score,
            "readiness_level": readiness_level,
            "vo2max": vo2max_value,
        },
        "sleep_trend": sleep_trend,
        "hrv_trend": hrv_trend,
        "activities": activities_out,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    log(f"Saved {OUT_FILE}")

    if DEBUG:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, default=str)
        log(f"Saved raw debug data to {DEBUG_FILE}")

    log("Done. Refresh the dashboard in your browser to see it.")


if __name__ == "__main__":
    main()
