import requests
from datetime import datetime, timedelta


def get_historical_cloud_cover(lat, lon, acq_date, acq_time):
    """
    LAYER 3: The Atmospheric Multiplier.
    Dynamically fetches historical cloud cover for the exact hour of the satellite overpass.
    """
    print(f" -> Target Location: Lat {lat}, Lon {lon}")
    print(f" -> Target Satellite Time (UTC): {acq_date} at {acq_time}")

    # 1. TIME PARSING: NASA acq_time is a weird integer (e.g., 1435 means 14:35)
    # We must format it into a proper datetime object and round to the nearest hour.
    time_str = str(acq_time).zfill(4)  # Ensures '930' becomes '0930'
    datetime_str = f"{acq_date} {time_str}"

    try:
        dt_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H%M")
        # Round to nearest hour for the API
        if dt_obj.minute >= 30:
            dt_obj += timedelta(hours=1)
        dt_obj = dt_obj.replace(minute=0, second=0)

        api_date = dt_obj.strftime("%Y-%m-%d")
        api_hour_iso = dt_obj.strftime("%Y-%m-%dT%H:00")
        print(f" -> Nearest API Hourly Block: {api_hour_iso}")

    except ValueError as e:
        print(f" [!] Time formatting error: {e}")
        return 0

    # 2. API PING: Requesting the exact historical date for that coordinate
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={api_date}&end_date={api_date}"
        f"&hourly=cloudcover"
    )

    print(f" -> Pinging Open-Meteo API...")
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        # 3. DATA EXTRACTION: Find the specific hour in the API response array
        times = data['hourly']['time']
        clouds = data['hourly']['cloudcover']

        if api_hour_iso in times:
            index = times.index(api_hour_iso)
            cloud_pct = clouds[index]
            print(f" -> SUCCESS: Cloud Cover at exact overpass was {cloud_pct}%")
            return cloud_pct
        else:
            print(" [!] Could not find matching hour in API response.")
            return 0

    except Exception as e:
        print(f" [!] API Connection Failed: {e}")
        return 0


if __name__ == "__main__":
    print("--- LAYER 3: WEATHER API TEST ---")

    # We are using the exact coordinates of your monster fire (Row 411)
    # NOTE: Look at your original CSV or terminal to get the exact acq_date and acq_time for Row 411.
    # I am using placeholder time here. Replace it with the real acq_date and acq_time!

    test_lat = 24.50780
    test_lon = 54.01567

    # YOU MUST CHANGE THESE TO MATCH ROW 411 IN YOUR DATASET
    test_date = "2024-04-18"
    test_time = 1030

    cloud_result = get_historical_cloud_cover(test_lat, test_lon, test_date, test_time)