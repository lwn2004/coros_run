import json
import time
from datetime import datetime
import os
import json
import re
import pytz
from opencc import OpenCC
import polyline
from math import sqrt

try:
    from rich import print
except:
    pass
from generator import Generator
from stravalib.client import Client
from stravalib.exc import RateLimitExceeded

cc = OpenCC('t2s')  # 繁体转简体
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
routeSVG = os.path.join(parent, "public", "images", "routesvg")

def adjust_time(time, tz_name):
    tc_offset = datetime.now(pytz.timezone(tz_name)).utcoffset()
    return time + tc_offset


def adjust_time_to_utc(time, tz_name):
    tc_offset = datetime.now(pytz.timezone(tz_name)).utcoffset()
    return time - tc_offset


def adjust_timestamp_to_utc(timestamp, tz_name):
    tc_offset = datetime.now(pytz.timezone(tz_name)).utcoffset()
    delta = int(tc_offset.total_seconds())
    return int(timestamp) - delta


def to_date(ts):
    # TODO use https://docs.python.org/3/library/datetime.html#datetime.datetime.fromisoformat
    # once we decide to move on to python v3.7+
    ts_fmts = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]

    for ts_fmt in ts_fmts:
        try:
            # performance with using exceptions
            # shouldn't be an issue since it's an offline cmdline tool
            return datetime.strptime(ts, ts_fmt)
        except ValueError:
            print(
                f"Warning: Can not execute strptime {ts} with ts_fmt {ts_fmt}, try next one..."
            )
            pass

    raise ValueError(f"cannot parse timestamp {ts} into date with fmts: {ts_fmts}")
  
def get_city_name(text):
    if text == None:
      return '未知'
    text = cc.convert(text)
    pattern = re.compile(r'(澳门|香港|[\u4e00-\u9fa5]{2,}(市|自治州|特别行政区|盟|地区))')
    match = pattern.search(text)
    return match.group(1) if match else '未知'

def make_activities_file(
    sql_file, data_dir, json_file, file_suffix="gpx", activity_title_dict=None, json_file2=None
):
    print("json_file: ", json_file)
    print("json file2: ", json_file2)
    generator = Generator(sql_file)
    generator.sync_from_data_dir(
        data_dir, file_suffix=file_suffix, activity_title_dict=activity_title_dict
    )
    activities_list = generator.load()
    with open(json_file, "w") as f:
        json.dump(activities_list, f)
    processed = []
    for activity in activities_list:
      if(activity["summary_polyline"]):
        polyline2svg(activity["summary_polyline"], os.path.join(routeSVG, str(activity["run_id"]) + ".svg"))
      #print(activity["start_date_local"])
      location = activity.get("location_country", "")
      city = get_city_name(location)
      #print(city)
      activity["city"] = city
      processed.append(activity)
      skip_columns = {"summary_polyline", "start_date", "location_country"}
      filtered_runs = [
        {k: v for k, v in rec.items() if k not in skip_columns}
        for rec in processed
      ]
    with open(json_file2, "w") as f:
      json.dump(filtered_runs,f)


def make_strava_client(client_id, client_secret, refresh_token):
    client = Client()

    refresh_response = client.refresh_access_token(
        client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
    )
    client.access_token = refresh_response["access_token"]
    return client


def get_strava_last_time(client, is_milliseconds=True):
    """
    if there is no activities cause exception return 0
    """
    try:
        activity = None
        activities = client.get_activities(limit=10)
        activities = list(activities)
        activities.sort(key=lambda x: x.start_date, reverse=True)
        # for else in python if you don't know please google it.
        for a in activities:
            if a.type == "Run":
                activity = a
                break
        else:
            return 0
        end_date = activity.start_date + activity.elapsed_time
        last_time = int(datetime.timestamp(end_date))
        if is_milliseconds:
            last_time = last_time * 1000
        return last_time
    except Exception as e:
        print(f"Something wrong to get last time err: {str(e)}")
        return 0


def upload_file_to_strava(client, file_name, data_type, force_to_run=True):
    with open(file_name, "rb") as f:
        try:
            if force_to_run:
                r = client.upload_activity(
                    activity_file=f, data_type=data_type, activity_type="run"
                )
            else:
                r = client.upload_activity(activity_file=f, data_type=data_type)

        except RateLimitExceeded as e:
            timeout = e.timeout
            print()
            print(f"Strava API Rate Limit Exceeded. Retry after {timeout} seconds")
            print()
            time.sleep(timeout)
            if force_to_run:
                r = client.upload_activity(
                    activity_file=f, data_type=data_type, activity_type="run"
                )
            else:
                r = client.upload_activity(activity_file=f, data_type=data_type)
        print(
            f"Uploading {data_type} file: {file_name} to strava, upload_id: {r.upload_id}."
        )
# --- Step 1: Ramer–Douglas–Peucker simplification ---
def perpendicular_distance(pt, line_start, line_end):
    if line_start == line_end:
        return sqrt((pt[0]-line_start[0])**2 + (pt[1]-line_start[1])**2)
    x0,y0 = pt
    x1,y1 = line_start
    x2,y2 = line_end
    num = abs((y2-y1)*x0 - (x2-x1)*y0 + x2*y1 - y2*x1)
    den = sqrt((y2-y1)**2 + (x2-x1)**2)
    return num/den

def rdp(points, epsilon):
    if len(points) < 3:
        return points
    dmax, index = 0, 0
    for i in range(1, len(points)-1):
        d = perpendicular_distance(points[i], points[0], points[-1])
        if d > dmax:
            index, dmax = i, d
    if dmax > epsilon:
        left = rdp(points[:index+1], epsilon)
        right = rdp(points[index:], epsilon)
        return left[:-1] + right
    else:
        return [points[0], points[-1]]

def polyline2svg(encoded_polyline, svgpath):
  points = polyline.decode(encoded_polyline)
  simplified = rdp(points, epsilon=0.0001)
  # Normalize + scale ---
  lats, lngs = zip(*simplified)
  min_x, max_x = min(lngs), max(lngs)
  min_y, max_y = min(lats), max(lats)
  width, height = 500, 500
  def scale_coords(x, y):
    nx = (x - min_x) / (max_x - min_x) if max_x > min_x else 0.5
    ny = (y - min_y) / (max_y - min_y) if max_y > min_y else 0.5
    ny = 1 - ny
    return int(nx * width), int(ny * height)  # integers only
  coords = [scale_coords(lng, lat) for lat, lng in simplified]
  #Build compact path ---
  path_cmds = [f"M{coords[0][0]},{coords[0][1]}"]
  for (x1,y1),(x2,y2) in zip(coords, coords[1:]):
    dx, dy = x2-x1, y2-y1
    path_cmds.append(f"l{dx},{dy}")
  path_data = "".join(path_cmds)

  #Write SVG ---
  svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><path d="{path_data}" fill="none" stroke="currentColor" stroke-width="8"/></svg>'
  with open(svgpath, "w") as f:
    f.write(svg)

