import argparse
import asyncio
import hashlib
import os
import time

import aiofiles
import httpx

import json
import fitparse
import requests
import polyline
from datetime import datetime, timezone, timedelta

from config import JSON_FILE, JSON_FILE2, SQL_FILE, FIT_FOLDER
from utils import make_activities_file

COROS_URL_DICT = {
    "LOGIN_URL": "https://teamcnapi.coros.com/account/login",
    "DOWNLOAD_URL": "https://teamcnapi.coros.com/activity/detail/download",
    "ACTIVITY_LIST": "https://teamcnapi.coros.com/activity/query?&modeList=100,102,103",
    "DASHBOARD":"https://teamcnapi.coros.com/dashboard/query",
}

TIME_OUT = httpx.Timeout(240.0, connect=360.0)

# --- Configuration ---
# WMO Weather code to human-readable description and icon
WMO_CODE_MAP = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅️"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "💧"), 53: ("Moderate drizzle", "💧"), 55: ("Dense drizzle", "💧"),
    56: ("Light freezing drizzle", "❄️💧"), 57: ("Dense freezing drizzle", "❄️💧"),
    61: ("Slight rain", "🌧️"), 63: ("Moderate rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "❄️🌧️"), 67: ("Heavy freezing rain", "❄️🌧️"),
    71: ("Slight snow fall", "🌨️"), 73: ("Moderate snow fall", "🌨️"), 75: ("Heavy snow fall", "🌨️"),
    77: ("Snow grains", "🌨️"), 80: ("Slight rain showers", "🌦️"), 81: ("Moderate rain showers", "🌦️"),
    82: ("Violent rain showers", "🌦️"), 85: ("Slight snow showers", "❄️"), 86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm with slight hail", "⛈️"), 99: ("Thunderstorm with heavy hail", "⛈️"),
}
WMO_CODE_MAP_ZH = {
    0: ("晴朗", "☀️"),    1: ("大部晴朗", "🌤️"),    2: ("局部多云", "⛅️"),
    3: ("阴天", "☁️"),    45: ("有雾", "🌫️"),    48: ("雾凇", "🌫️"),
    51: ("小毛毛雨", "💧"),    53: ("中等毛毛雨", "💧"),    55: ("大毛毛雨", "💧"),
    56: ("轻微冻毛毛雨", "❄️💧"),    57: ("强冻毛毛雨", "❄️💧"),
    61: ("小雨", "🌧️"),    63: ("中雨", "🌧️"),    65: ("大雨", "🌧️"),
    66: ("小冻雨", "❄️🌧️"),    67: ("大冻雨", "❄️🌧️"),
    71: ("小雪", "🌨️"),    73: ("中雪", "🌨️"),    75: ("大雪", "🌨️"),
    77: ("雪粒", "🌨️"),    80: ("小阵雨", "🌦️"),    81: ("中阵雨", "🌦️"),
    82: ("强阵雨", "🌦️"),    85: ("小阵雪", "❄️"),    86: ("大阵雪", "❄️"),
    95: ("雷暴", "⛈️"),    96: ("雷暴伴轻冰雹", "⛈️"),    99: ("雷暴伴强冰雹", "⛈️"),
}

TARGET_CHART_POINTS = 150 # Number of data points for charts

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
details_folder = os.path.join(parent, "public", "data", "details")

class Coros:
    def __init__(self, account, password):
        self.account = account
        self.password = password
        self.headers = None
        self.req = None

    async def login(self):
        url = COROS_URL_DICT.get("LOGIN_URL")
        headers = {
            "authority": "teamcnapi.coros.com",
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "content-type": "application/json;charset=UTF-8",
            "dnt": "1",
            "origin": "https://t.coros.com",
            "referer": "https://t.coros.com/",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        }
        data = {"account": self.account, "accountType": 2, "pwd": self.password}
        async with httpx.AsyncClient(timeout=TIME_OUT) as client:
            response = await client.post(url, json=data, headers=headers)
            resp_json = response.json()
            access_token = resp_json.get("data", {}).get("accessToken")
            if not access_token:
                raise Exception(
                    "============Login failed! please check your account and password==========="
                )
            self.headers = {
                "accesstoken": access_token,
                "cookie": f"CPL-coros-region=2; CPL-coros-token={access_token}",
            }
            self.req = httpx.AsyncClient(timeout=TIME_OUT, headers=self.headers)
        await client.aclose()

    async def init(self):
        await self.login()

    async def fetch_activity_ids(self):
        page_number = 1
        all_activities_ids = []

        while True:
            url = f"{COROS_URL_DICT.get('ACTIVITY_LIST')}&pageNumber={page_number}&size=20"
            response = await self.req.get(url)
            data = response.json()
            activities = data.get("data", {}).get("dataList", None)
            if not activities:
                break
            for activity in activities:
                label_id = activity["labelId"]
                if label_id is None:
                    continue
                all_activities_ids.append(label_id)

            page_number += 1

        return all_activities_ids

    async def download_activity(self, label_id):
        download_folder = FIT_FOLDER
        download_url = f"{COROS_URL_DICT.get('DOWNLOAD_URL')}?labelId={label_id}&sportType=100&fileType=4"
        file_url = None
        try:
            response = await self.req.post(download_url)
            resp_json = response.json()
            file_url = resp_json.get("data", {}).get("fileUrl")
            if not file_url:
                print(f"No file URL found for label_id {label_id}")
                return None, None

            fname = os.path.basename(file_url)
            file_path = os.path.join(download_folder, fname)

            async with self.req.stream("GET", file_url) as response:
                response.raise_for_status()
                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        await f.write(chunk)
        except httpx.HTTPStatusError as exc:
            print(
                f"Failed to download {file_url} with status code {response.status_code}: {exc}"
            )
            return None, None
        except Exception as exc:
            print(f"Error occurred while downloading {file_url}: {exc}")
            return None, None

        return label_id, fname


def get_downloaded_ids(folder):
    return [i.split(".")[0] for i in os.listdir(folder) if not i.startswith(".")]


async def download_and_generate(account, password):
    folder = FIT_FOLDER
    downloaded_ids = get_downloaded_ids(folder)
    coros = Coros(account, password)
    await coros.init()

    activity_ids = await coros.fetch_activity_ids()
    print("activity_ids: ", len(activity_ids))
    print("downloaded_ids: ", len(downloaded_ids))
    to_generate_coros_ids = list(set(activity_ids) - set(downloaded_ids))
    print("to_generate_activity_ids: ", len(to_generate_coros_ids))

    start_time = time.time()
    await gather_with_concurrency(
        10,
        [coros.download_activity(label_d) for label_d in to_generate_coros_ids],
    )
    print(f"Download finished. Elapsed {time.time()-start_time} seconds")
    await coros.req.aclose()
    make_activities_file(SQL_FILE, FIT_FOLDER, JSON_FILE, "fit", json_file2 = JSON_FILE2)

    for label_id in ['471277511687307274', '471277511687307273', '471374084024861075', '471348054109225065']: #to_generate_coros_ids: #
      fit_path = os.path.join(folder, f"{label_id}.fit")
      run_data = parse_fit_file(fit_path)
  
      if run_data:
        output_filename = os.path.join(details_folder, f"{label_id}.json")
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(run_data, f, indent=4, ensure_ascii=False)
        print(f"Successfully processed run data. Saved to {output_filename}")


async def gather_with_concurrency(n, tasks):
    semaphore = asyncio.Semaphore(n)

    async def sem_task(task):
        async with semaphore:
            return await task

    return await asyncio.gather(*(sem_task(task) for task in tasks))

# --- Helper Functions ---
def semicircles_to_degrees(semicircles):
    """Converts Garmin's semicircle format to degrees."""
    if semicircles is None:
        return None
    return semicircles * (180 / 2**31)

def format_duration(seconds):
    """Formats seconds into HH:MM:SS."""
    if seconds is None: return "00:00:00"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"

def format_pace(speed_mps):
    """Converts speed in m/s to pace string min'sec"/km."""
    if speed_mps is None or speed_mps == 0:
        return "0'00\""
    pace_sec_per_km = 1000 / speed_mps
    minutes = int(pace_sec_per_km // 60)
    seconds = int(pace_sec_per_km % 60)
    return f"{minutes}'{seconds:02}\""

def get_weather_data(lat, lon, timestamp):
    """Fetches historical weather, with a fallback to the forecast API for recent data."""
    if lat is None or lon is None or timestamp is None:
        return None
    
    dt_utc = timestamp.replace(tzinfo=timezone.utc)
    date_str = dt_utc.strftime("%Y-%m-%d")

    # 1. First, try the Archive API (best for data older than a few hours)
    archive_api_url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&start_date={date_str}&end_date={date_str}"
        f"&hourly=temperature_2m,weathercode,windspeed_10m"
    )
    try:
        res = requests.get(archive_api_url, timeout=10)
        res.raise_for_status()
        data = res.json()
        print(json.dumps(data, indent=4, sort_keys=True))
        if data.get('hourly') and data['hourly'].get('time'):
            hour_index = dt_utc.hour
            temp = data['hourly']['temperature_2m'][hour_index]
            code = data['hourly']['weathercode'][hour_index]
            wind_kmh = data['hourly']['windspeed_10m'][hour_index]
            condition, icon = WMO_CODE_MAP_ZH.get(code, ("Unknown", ""))
            print("Successfully fetched weather from Archive API.")
            return {
                "temperature_c": temp,
                "condition": f"{condition} {icon}",
                "wind_speed_kmh": wind_kmh
            }
    except Exception as e:
        print(f"Archive API failed for {date_str}: {e}. Will try Forecast API as a fallback.")

    # 2. Fallback to Forecast API for recent dates (within the last 5 days)
    if (datetime.now(timezone.utc) - dt_utc).days < 5:
        print("Date is recent, attempting Forecast API fallback...")
        forecast_api_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&hourly=temperature_2m,weathercode,windspeed_10m&past_days=5"
        )
        try:
            res = requests.get(forecast_api_url, timeout=10)
            res.raise_for_status()
            data = res.json()
            # Find the matching timestamp in the forecast data
            target_iso_time = dt_utc.strftime("%Y-%m-%dT%H:00")
            if target_iso_time in data['hourly']['time']:
                idx = data['hourly']['time'].index(target_iso_time)
                temp = data['hourly']['temperature_2m'][idx]
                code = data['hourly']['weathercode'][idx]
                wind_kmh = data['hourly']['windspeed_10m'][idx]
                condition, icon = WMO_CODE_MAP_ZH.get(code, ("Unknown", ""))
                print("Successfully fetched weather from Forecast API fallback.")
                return {
                    "temperature_c": temp,
                    "condition": f"{condition} {icon}",
                    "wind_speed_kmh": wind_kmh
                }
        except Exception as e:
            print(f"Forecast API fallback also failed: {e}")
            
    return None

def downsample_records(records, target_points):
    """Downsamples a list of record dictionaries with correct pace/speed averaging."""
    if not records or len(records) <= target_points:
        return records
    
    downsampled = []
    chunk_size = len(records) / target_points
    for i in range(target_points):
        start = int(i * chunk_size)
        end = int((i + 1) * chunk_size)
        chunk = records[start:end]
        if not chunk: continue

        avg_point = {}
        first_record = chunk[0]
        last_record = chunk[-1]

        # Correctly calculate average speed from total distance and time for the chunk
        time_delta_seconds = (last_record.get('timestamp') - first_record.get('timestamp')).total_seconds()
        dist_delta_meters = last_record.get('distance', 0) - first_record.get('distance', 0)

        if time_delta_seconds > 0 and dist_delta_meters > 0:
            avg_point['speed'] = dist_delta_meters / time_delta_seconds
        else:
            avg_point['speed'] = first_record.get('speed')  # Fallback to first point if no change

        # Average other numeric keys, sample non-numeric keys
        for key in first_record.keys():
            if key == 'speed': continue  # Already handled

            valid_values = [p[key] for p in chunk if p.get(key) is not None]
            if valid_values:
                if isinstance(valid_values[0], (int, float)):
                    avg_point[key] = sum(valid_values) / len(valid_values)
                else:
                    avg_point[key] = valid_values[0]
            else:
                avg_point[key] = None
        downsampled.append(avg_point)
    return downsampled

def parse_fit_file(fit_file_path):
    """Parses a FIT file and returns a structured dictionary for the run detail modal."""
    try:
        fitfile = fitparse.FitFile(fit_file_path)
    except Exception as e:
        print(f"Error opening FIT file: {e}")
        return None

    records, laps, session, file_id = [], [], None, None

    for message in fitfile.get_messages():
        #if message.name == "record" and message.has_field('position_lat') and message.has_field('position_long'):
        if message.name == "record" and message.get_value('position_lat') is not None and message.get_value('position_long') is not None:
          records.append(message.get_values())
        elif message.name == "lap":
            laps.append(message.get_values())
        elif message.name == "session":
            session = message.get_values()
        elif message.name == "file_id":
            file_id = message.get_values()

    if not session or not records or not file_id:
        print("FIT file is missing essential data (session, records, or file_id).")
        return None

    # --- Basic Info & Weather ---
    run_id = int(file_id.get('time_created').timestamp())
    start_time = session.get('start_time')
    first_lat = semicircles_to_degrees(records[0].get('position_lat'))
    first_lon = semicircles_to_degrees(records[0].get('position_long'))
    
    print(f"Run ID: {run_id}")
    print(f"Fetching weather for {start_time} at ({first_lat:.4f}, {first_lon:.4f})...")
    weather = get_weather_data(first_lat, first_lon, start_time)

    # --- Route Polyline ---
    coords = [
        (semicircles_to_degrees(r.get('position_lat')), semicircles_to_degrees(r.get('position_long')))
        for r in records
    ]
    encoded_polyline = polyline.encode(coords)
    
    # --- Summary ---
    total_distance_km = session.get('total_distance', 0) / 1000
    total_duration_sec = session.get('total_elapsed_time', 0)
    avg_speed_mps = session.get('avg_speed')
    best_speed_mps = session.get('max_speed')
    ave_cadence = session.get('avg_running_cadence') *2
    
    summary = {
        "distance_km": f"{total_distance_km:.2f}",
        "duration": format_duration(total_duration_sec),
        "avg_pace": format_pace(avg_speed_mps),
        "best_pace": format_pace(best_speed_mps),
        "calories_kcal": session.get('total_calories'),
        "total_ascent_m": session.get('total_ascent'),
        "avg_cadence": ave_cadence,
        "avg_power_w": session.get('avg_power'),
        "avg_hr": session.get('avg_heart_rate'),
        "max_hr": session.get('max_heart_rate')
    }
    
    # --- Laps ---
    processed_laps = []
    for i, lap in enumerate(laps, 1):
        lap_dist_km = lap.get('total_distance', 0) / 1000
        lap_time_sec = lap.get('total_elapsed_time', 0)
        ave_cadence = lap.get('avg_running_cadence') *2
        processed_laps.append({
            "lap_number": i,
            "duration": format_duration(lap_time_sec),
            "distance_km": f"{lap_dist_km:.2f}",
            "pace": format_pace(lap.get('avg_speed')),
            "avg_hr": lap.get('avg_heart_rate'),
            "avg_cadence": ave_cadence
        })

    # --- Charts ---
    chart_records = downsample_records(records, TARGET_CHART_POINTS)
    
    def create_chart_data(key, label_unit, value_transform=lambda x: x):
        labels = []
        data = []
        for r in chart_records:
            if r.get('distance') is not None and r.get(key) is not None:
                labels.append(f"{r['distance']/1000:.1f}{label_unit}")
                data.append(value_transform(r[key]))
        return {"labels": labels, "data": data}

    pace_chart_data = create_chart_data('speed', 'km', lambda s: 1000 / s if s > 0 else 0)
    elevation_chart_data = create_chart_data('altitude', 'km')
    hr_chart_data = create_chart_data('heart_rate', 'km')
    
    # --- Final Assembly ---
    run_detail = {
        "run_id": run_id,
        "start_time": start_time.isoformat(),
        "weather": weather,
        "route": {"encoded_polyline": encoded_polyline},
        "summary": summary,
        "laps": processed_laps,
        "charts": {
            "pace": pace_chart_data,
            "elevation": elevation_chart_data,
            "hr": hr_chart_data
        },
        "photos": [
            {"url": f"https://picsum.photos/seed/{run_id}_a/600/400"},
            {"url": f"https://picsum.photos/seed/{run_id}_b/600/400"}
        ]
    }
    
    return run_detail


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("account", nargs="?", help="input coros account")

    parser.add_argument("password", nargs="?", help="input coros password")
    options = parser.parse_args()

    account = options.account
    password = options.password
    encrypted_pwd = hashlib.md5(password.encode()).hexdigest()

    asyncio.run(download_and_generate(account, encrypted_pwd))
