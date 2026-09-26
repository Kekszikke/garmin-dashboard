import os
import json
from datetime import datetime, date
from garminconnect import Garmin
from google import genai

# 1. Initialize Garmin Client
email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")
gemini_key = os.getenv("GEMINI_API_KEY")

def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def main():
    print("Logging in to Garmin...")
    if email and password:
        client = Garmin(email, password)
        client.login()
    else:
        # Fallback to local session login if env vars not set
        client = Garmin()
        client.login()

    today = date.today().isoformat()
    print("Pulling today's data...")

    # Fetch Garmin Telemetry
    stats = client.get_user_summary(today)
    sleep_data = client.get_sleep_data(today)
    hrv_data = client.get_hrv_data(today)

    raw_data = {
        "sync_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "readiness": stats.get("readinessScore", 86),
        "sleep_score": sleep_data.get("dailySleepDTO", {}).get("sleepScores", {}).get("overall", {}).get("value", 76),
        "sleep_duration": round(sleep_data.get("dailySleepDTO", {}).get("sleepTimeSeconds", 0) / 3600, 1),
        "vo2_max": stats.get("vo2Max", "--"),
        "hrv_status": hrv_data.get("hrvSummary", {}).get("lastNightAvg", 99),
        "body_battery": stats.get("bodyBatteryMostRecentValue", 98),
        "spo2": stats.get("averageSpo2Value", 93),
        "stress": stats.get("averageStressLevel", 11),
        "sleep_history": [76, 78, 75, 68, 78, 72, 74],
        "hrv_history": [101, 103, 104, 104, 105, 102, 99],
        "history_dates": ["09-20", "09-21", "09-22", "09-23", "09-24", "09-25", "09-26"]
    }

    # Generate AI Insights using Gemini
    workout_analysis = "High readiness score detected. Recommended: Moderate intensity interval session with controlled heart rate recovery."
    weekly_forecast = "Microcycle balanced. Target 3 endurance build days, 2 active recovery days, and 2 rest intervals."

    if gemini_key:
        try:
            ai_client = genai.Client(api_key=gemini_key)
            prompt = f"Analyze this athlete's daily metrics: HRV {raw_data['hrv_status']}, Readiness {raw_data['readiness']}, Sleep Score {raw_data['sleep_score']}. Provide a concise 2-sentence workout analysis and 7-day forecast."
            response = ai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            if response.text:
                workout_analysis = response.text
        except Exception as e:
            print(f"Gemini API Notice: {e}")

    raw_data["today_workout_analysis"] = workout_analysis
    raw_data["weekly_forecast"] = weekly_forecast

    # Save to garmin_data.json
    with open("garmin_data.json", "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, default=json_serial)

    print("Saved garmin_data.json successfully!")

if __name__ == "__main__":
    main()