import json
from datetime import datetime, timedelta, date, timezone
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
import sys
import locale
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import matplotlib.pyplot as plt
import io
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
# --- Configuration ---
CITIES_FILE_PATH = os.path.join(parent, "src", "static", "cities.json")

def load_city_coordinates(path):
    """从指定路径加载城市坐标JSON文件"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"错误：找不到城市坐标文件 {path}")
        return {}
    except json.JSONDecodeError:
        print(f"错误：无法解析城市坐标文件 {path}，请检查JSON格式。")
        return {}

# --- 您的主配置 ---
CONFIG = {
    "earth_circumference_km": 40075.017,
    "pb_type_map": {
        1: "全马", 2: "半马", 3: "15公里", 4: "10公里", 5: "5公里",
        6: "3公里", 7: "1公里", 8: "1英里", 9: "2英里", 10: "3英里",
        11: "5英里", 12: "10英里"
    },
    "pb_display_order": ["1公里", "3公里", "5公里", "10公里", "半马", "全马"],
    "milestone_distances_km": [1000, 10000, 20000, 30000, 40000],
    "months_map": {i: f"{i:02d}月" for i in range(1, 13)},
    
    # 通过调用函数来加载城市坐标
    "city_coordinates": load_city_coordinates(CITIES_FILE_PATH)
}

# --- Formatting Utilities ---
def setup_locale():
    try:
        if sys.platform.startswith('win'):
            locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
        else:
            locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except locale.Error:
        print("Warning: Could not set locale. Date formatting may be incorrect.")

def parse_duration(s: str) -> timedelta:
    try:
        h, m, sec = map(float, s.split(":"))
        return timedelta(hours=h, minutes=m, seconds=sec)
    except (ValueError, TypeError):
        return timedelta()

def format_duration(td: timedelta) -> str:
    if not isinstance(td, timedelta): return "0:00:00"
    total_seconds = int(td.total_seconds())
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}"

def format_pace_from_seconds(pace_seconds: float) -> str:
    if pace_seconds <= 0: return "--"
    minutes = int(pace_seconds // 60)
    seconds = int(pace_seconds % 60)
    return f"{minutes}'{seconds:02}\""

def format_pace_from_mps(speed_mps: float) -> str:
    if speed_mps <= 0: return "--"
    return format_pace_from_seconds(1000 / speed_mps)

def format_timedelta_for_display(days: int) -> str:
    years = days // 365
    remaining_days = days % 365
    return f"{years}年{remaining_days}天"

# --- Data Loading and Processing Functions ---
def load_json_file(file_path: str, is_list: bool = True):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if is_list and not isinstance(data, list):
                return [data]
            return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading '{file_path}': {e}")
        return [] if is_list else {}

def load_run_data(file_path: str):
    runs_data = load_json_file(file_path)
    all_runs = []
    fastest_run = None

    for run in runs_data:
        processed_run = {
            "id": run.get("run_id", datetime.now().timestamp()),
            "date": datetime.strptime(run["start_date_local"], "%Y-%m-%d %H:%M:%S"),
            "distance": float(run.get("distance", 0)),
            "duration": parse_duration(run.get("moving_time", "0:0:0")),
            "average_speed": float(run.get("average_speed", 0)),
            "city": run.get("city", "未知"),
            "heart_rate": int(hr) if (hr := run.get("average_heartrate")) else "未知",
            "streak": run.get("streak", 1),
        }
        processed_run["pace"] = format_pace_from_mps(processed_run["average_speed"])
        processed_run["start_time"] = processed_run["date"].strftime('%H:%M:%S')
        all_runs.append(processed_run)

        if processed_run['distance'] > 1000 and (fastest_run is None or processed_run['average_speed'] > fastest_run['average_speed']):
            fastest_run = processed_run
            
    return sorted(all_runs, key=lambda r: r['date']), fastest_run

def load_pb_data(file_path: str):
    pb_records = load_json_file(file_path)
    personal_bests = {}
    
    for record in pb_records:
        record_type = record.get("type")
        if label := CONFIG["pb_type_map"].get(record_type):
            try:
                date_obj = datetime.strptime(str(record.get("happenDay", 0)), '%Y%m%d')
                date_str = date_obj.strftime('%Y年%m月%d日')
            except ValueError:
                date_str = "无记录"
            
            personal_bests[label] = {
                "time": format_duration(timedelta(seconds=record.get("duration", 0))),
                "pace": format_pace_from_seconds(record.get("avgPace", 0)),
                "date": date_str
            }
    
    for label in CONFIG["pb_display_order"]:
        if label not in personal_bests:
            personal_bests[label] = {"time": "--", "pace": "--", "date": "无记录"}
    
    return {label: personal_bests[label] for label in CONFIG["pb_display_order"]}

def load_events_data(file_path: str):
    events_data = load_json_file(file_path)
    processed_events = []

    for event in events_data:
        try:
            duration_td = parse_duration(event.get("duration", "0:0:0"))
            distance_km = float(event.get("distance", 0)) / 1000
            pace_str = format_pace_from_seconds(duration_td.total_seconds() / distance_km) if distance_km > 0 else "--"
        except Exception:
            pace_str = "--"

        processed_events.append({
            "name": event.get("name", "未知赛事"),
            "category": event.get("category", ""),
            "city": event.get("city", ""),
            "distance": distance_km,
            "date": datetime.strptime(event["happenDay"], "%Y-%m-%d") if event.get("happenDay") else None,
            "duration": duration_td,
            "pace": pace_str,
            "certified": event.get("certified", ""),
            "certificate": event.get("certificate", "")
        })
    
    return sorted(processed_events, key=lambda x: x["date"] or datetime.min, reverse=True)

def summarize_runs(runs_list):
    if not runs_list:
        return {"count": 0, "dist_km": 0, "duration_str": "0:00:00", "pace": "--", "avg_dist_per_run": 0}
    
    count = len(runs_list)
    total_dist_m = sum(r['distance'] for r in runs_list)
    total_duration_sec = sum(r['duration'].total_seconds() for r in runs_list)
    
    avg_speed_mps = total_dist_m / total_duration_sec if total_duration_sec > 0 else 0
    dist_km = total_dist_m / 1000
    
    return {
        "count": count,
        "dist_km": dist_km,
        "duration_str": format_duration(timedelta(seconds=total_duration_sec)),
        "pace": format_pace_from_mps(avg_speed_mps),
        "avg_dist_per_run": dist_km / count
    }

def get_week_start(year, week):
    """Returns the date of the Monday for a given ISO week."""
    return datetime.fromisocalendar(year, week, 1).date()

def calculate_streaks(all_runs):
    """
    Calculates the longest and current weekly running streaks.
    A week is defined as Monday to Sunday (ISO week).
    """
    if not all_runs:
        return {
            'current_streak': {'weeks': 0, 'start_date': '', 'end_date': ''},
            'longest_streak': {'weeks': 0, 'start_date': '', 'end_date': ''}
        }

    run_weeks = sorted(list(set(run['date'].isocalendar()[:2] for run in all_runs)))

    if not run_weeks:
        return {
            'current_streak': {'weeks': 0, 'start_date': '', 'end_date': ''},
            'longest_streak': {'weeks': 0, 'start_date': '', 'end_date': ''}
        }

    longest_streak = 0
    current_streak = 0
    longest_streak_start_week = None
    longest_streak_end_week = None

    for i in range(len(run_weeks)):
        if i == 0:
            current_streak = 1
        else:
            prev_year, prev_week = run_weeks[i-1]
            curr_year, curr_week = run_weeks[i]
            
            is_consecutive = False
            if curr_year == prev_year and curr_week == prev_week + 1:
                is_consecutive = True
            elif curr_year == prev_year + 1 and curr_week == 1:
                 last_week_of_prev_year = date(prev_year, 12, 28).isocalendar()[1]
                 if prev_week == last_week_of_prev_year:
                     is_consecutive = True
            
            if is_consecutive:
                current_streak += 1
            else:
                current_streak = 1
        
        if current_streak > longest_streak:
            longest_streak = current_streak
            longest_streak_end_week = run_weeks[i]
            longest_streak_start_week = run_weeks[i - current_streak + 1]

    today = date.today()
    current_iso_week = today.isocalendar()[:2]
    last_run_iso_week = run_weeks[-1]
    last_week_date = today - timedelta(days=7)
    last_iso_week = last_week_date.isocalendar()[:2]
    
    is_current = (last_run_iso_week == current_iso_week or last_run_iso_week == last_iso_week)

    final_current_streak_weeks = 0
    current_streak_start_date_str, current_streak_end_date_str = '', ''
    if is_current:
        final_current_streak_weeks = current_streak
        current_streak_start_week = run_weeks[len(run_weeks) - current_streak]
        
        start_date = get_week_start(current_streak_start_week[0], current_streak_start_week[1])
        end_date = get_week_start(last_run_iso_week[0], last_run_iso_week[1]) + timedelta(days=6)
        current_streak_start_date_str = start_date.strftime('%Y-%m-%d')
        current_streak_end_date_str = end_date.strftime('%Y-%m-%d')

    longest_streak_start_date_str, longest_streak_end_date_str = '', ''
    if longest_streak_start_week:
        start_date = get_week_start(longest_streak_start_week[0], longest_streak_start_week[1])
        end_date = get_week_start(longest_streak_end_week[0], longest_streak_end_week[1]) + timedelta(days=6)
        longest_streak_start_date_str = start_date.strftime('%Y-%m-%d')
        longest_streak_end_date_str = end_date.strftime('%Y-%m-%d')

    return {
        'current_streak': {
            'weeks': final_current_streak_weeks,
            'start_date': current_streak_start_date_str,
            'end_date': current_streak_end_date_str
        },
        'longest_streak': {
            'weeks': longest_streak,
            'start_date': longest_streak_start_date_str,
            'end_date': longest_streak_end_date_str
        }
    }


def prepare_template_context(all_runs, fastest_run, pb_file, events_file):
    if not all_runs:
        return {}

    events = load_events_data(events_file)
    long_runs = [run for run in all_runs if run['distance'] > 1000]
    recent_runs = list(reversed(long_runs[-3:]))
    
    city_stats_agg = defaultdict(lambda: {'count': 0, 'distance': 0.0, 'first_date': None})
    for run in all_runs:
        city = run['city']
        if city and city != '未知':
            city_data = city_stats_agg[city]
            city_data['count'] += 1
            city_data['distance'] += run['distance'] / 1000
            if city_data['first_date'] is None or run['date'] < city_data['first_date']:
                city_data['first_date'] = run['date']

    city_stats = [
        {'name': city, 'count': data['count'], 'distance': round(data['distance'], 2), 
         'coordinates': CONFIG["city_coordinates"].get(city, []),
         'first_date': data['first_date'].strftime('%Y-%m-%d') if data['first_date'] else ''}
        for city, data in city_stats_agg.items()
    ]
    city_stats.sort(key=lambda x: (x['count'], x['distance']), reverse=True)

    today = datetime.now().date()
    thirty_days_ago = today - timedelta(days=29)
    last_30_days_data = { (thirty_days_ago + timedelta(days=i)): 0.0 for i in range(30) }
    
    recent_runs_30_days = [r for r in all_runs if r['date'].date() >= thirty_days_ago]
    for run in recent_runs_30_days:
        run_date = run['date'].date()
        if run_date in last_30_days_data:
            last_30_days_data[run_date] += run['distance'] / 1000

    # --- START: Modified section for 30-day chart ---
    sorted_dates = sorted(last_30_days_data.keys())
    chart_30_days_labels = [d.strftime('%m-%d') for d in sorted_dates]
    chart_30_days_values = [round(last_30_days_data[d], 2) for d in sorted_dates]
    
    # Define colors based on the day of the week
    weekday_color = 'rgba(77, 171, 247, 0.6)'  # accent-color
    weekend_color = 'rgba(32, 201, 151, 0.6)' # success-color
    
    # Monday is 0 and Sunday is 6. Saturday is 5.
    chart_30_days_colors = [
        weekend_color if d.weekday() >= 5 else weekday_color
        for d in sorted_dates
    ]
    
    chart_30_days = {
        'labels': chart_30_days_labels, 
        'data': chart_30_days_values,
        'colors': chart_30_days_colors
    }
    # --- END: Modified section for 30-day chart ---


    overall_stats = summarize_runs(all_runs)
    one_year_ago = datetime.now() - timedelta(days=365)
    recent_runs_1_year = [r for r in all_runs if r['date'] >= one_year_ago]
    recent_stats = summarize_runs(recent_runs_1_year)

    by_year = defaultdict(lambda: defaultdict(list))
    for run in all_runs:
        by_year[run['date'].year][run['date'].month].append(run)
    
    summarized_by_year = {}
    for year, months in sorted(by_year.items(), reverse=True):
        year_runs = [run for month_runs in months.values() for run in month_runs]
        summarized_by_year[year] = {
            "summary": summarize_runs(year_runs), 
            "months": {},
            "all_runs": sorted(year_runs, key=lambda r: r['date'], reverse=True)
        }
        for month, runs in months.items():
            summarized_by_year[year]["months"][month] = {
                "summary": summarize_runs(runs),
                "runs": sorted(runs, key=lambda r: r['date'], reverse=True)
            }

    months_for_chart = []
    for year in sorted(by_year.keys(), reverse=True):
        for month in sorted(by_year[year].keys(), reverse=True):
            if len(months_for_chart) < 12:
                dist = summarized_by_year[year]["months"][month]["summary"]["dist_km"]
                months_for_chart.append(((year, month), dist))
    months_for_chart.reverse()
    
    progress = (overall_stats['dist_km'] / CONFIG["earth_circumference_km"]) * 100
    estimated_info = {'date_str': "数据不足", 'days_left': "--"}
    remaining_km = CONFIG["earth_circumference_km"] - overall_stats['dist_km']
    if remaining_km > 0 and recent_stats['dist_km'] > 0:
        km_per_day = recent_stats['dist_km'] / 365
        days_needed = int(remaining_km / km_per_day)
        estimated_date = datetime.now() + timedelta(days=days_needed)
        estimated_info['date_str'] = estimated_date.strftime("%Y年%m月%d日")
        estimated_info['days_left'] = format_timedelta_for_display(days_needed)
    elif remaining_km <= 0:
        estimated_info.update({'date_str': "已完成", 'days_left': "0年0天"})
        
    milestone_dates = {}
    cumulative_dist_km = 0
    for run in all_runs:
        cumulative_dist_km += run['distance'] / 1000
        for m_dist in CONFIG["milestone_distances_km"]:
            if m_dist not in milestone_dates and cumulative_dist_km >= m_dist:
                milestone_dates[m_dist] = run['date']

    years_for_chart = sorted(summarized_by_year.keys())
    chart_yearly_labels = [str(y) for y in years_for_chart]
    chart_yearly_data = [round(summarized_by_year[y]["summary"]["dist_km"], 2) for y in years_for_chart]
    
    current_year = today.year
    current_month = today.month
    current_day = today.day

    last_month_date = today.replace(day=1) - timedelta(days=1)
    last_month_year = last_month_date.year
    last_month = last_month_date.month

    current_month_runs = [r for r in all_runs if r['date'].year == current_year and r['date'].month == current_month]
    current_month_dist = sum(r['distance'] for r in current_month_runs) / 1000

    last_month_runs_to_date = [
        r for r in all_runs
        if r['date'].year == last_month_year
        and r['date'].month == last_month
        and r['date'].day <= current_day
    ]
    last_month_dist_to_date = sum(r['distance'] for r in last_month_runs_to_date) / 1000

    month_on_month_diff = current_month_dist - last_month_dist_to_date

    monthly_comparison = {
        "current_month_dist": round(current_month_dist, 2),
        "diff_km": round(month_on_month_diff, 2)
    }

    days_in_current_month_obj = (date(current_year, current_month % 12 + 1, 1) if current_month < 12 else date(current_year + 1, 1, 1)) - timedelta(days=1)
    num_days_for_chart = days_in_current_month_obj.day

    this_month_daily_cumulative = [0.0] * num_days_for_chart
    last_month_daily_cumulative = [0.0] * num_days_for_chart

    daily_dist_this = defaultdict(float)
    for run in current_month_runs:
        daily_dist_this[run['date'].day] += run['distance'] / 1000
    
    cumulative = 0.0
    for i in range(num_days_for_chart):
        cumulative += daily_dist_this.get(i + 1, 0.0)
        this_month_daily_cumulative[i] = round(cumulative, 2)

    last_month_runs_full = [r for r in all_runs if r['date'].year == last_month_year and r['date'].month == last_month]
    daily_dist_last = defaultdict(float)
    for run in last_month_runs_full:
        daily_dist_last[run['date'].day] += run['distance'] / 1000

    cumulative = 0.0
    for i in range(num_days_for_chart):
        cumulative += daily_dist_last.get(i + 1, 0.0)
        last_month_daily_cumulative[i] = round(cumulative, 2)

    chart_month_over_month = {
        'labels': [f"{i+1:02d}" for i in range(num_days_for_chart)],
        'this_month_data': this_month_daily_cumulative,
        'last_month_data': last_month_daily_cumulative,
        'summary': {
            'this_month_total': round(current_month_dist, 2),
            'diff_km': round(month_on_month_diff, 2)
        }
    }

    current_year_runs = [r for r in all_runs if r['date'].year == current_year]
    monthly_totals_this_year = [0.0] * 12
    for run in current_year_runs:
        monthly_totals_this_year[run['date'].month - 1] += run['distance'] / 1000
    
    monthly_totals_this_year = [round(d, 2) for d in monthly_totals_this_year]

    yearly_cumulative_data = []
    cumulative_dist = 0.0
    for monthly_dist in monthly_totals_this_year:
        cumulative_dist += monthly_dist
        yearly_cumulative_data.append(round(cumulative_dist, 2))

    chart_yearly_dual_axis = {
        'labels': [f"{m}月" for m in range(1, 13)],
        'monthly_data': monthly_totals_this_year,
        'cumulative_data': yearly_cumulative_data,
        'total': round(cumulative_dist, 2)
    }

    beijing_tz = timezone(timedelta(hours=8))
    last_build_time = datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

    return {
        "recent_runs": recent_runs,
        "overall_stats": overall_stats,
        "recent_stats": recent_stats,
        "summarized_by_year": summarized_by_year,
        "months_map": CONFIG["months_map"],
        "fastest_pace_info": {
            "pace": fastest_run['pace'] if fastest_run else "--",
            "date": fastest_run['date'].strftime('%Y-%m-%d') if fastest_run else "N/A"
        },
        "personal_bests": load_pb_data(pb_file),
        "events": events,
        "chart_monthly_labels": [f"{str(y)[-2:]}-{m:02d}" for (y, m), _ in months_for_chart],
        "chart_monthly_data": [round(dist, 2) for _, dist in months_for_chart],
        "chart_30_days": chart_30_days,
        "chart_yearly_labels": chart_yearly_labels,
        "chart_yearly_data": chart_yearly_data,		
        "progress_around_earth": progress,
        "estimated_info": estimated_info,
        "milestone_dates": milestone_dates,
        "first_run_date": all_runs[0]['date'],
        "first_run_distance": all_runs[0]['distance'] / 1000,
        "city_stats": city_stats,
        "streak_records": calculate_streaks(all_runs),
        "last_build_time": last_build_time,
        "monthly_comparison": monthly_comparison,
        "chart_month_over_month": chart_month_over_month,
        "chart_yearly_dual_axis": chart_yearly_dual_axis,
    }
def generate_share_card(bg_file, run_data, save_img_file):
  # ==== 1. open bg ====
  bg = Image.open(bg_file).convert("RGBA")
  W, H = bg.size
  
  # ==== 2. run data ====
  date_str = run_data['start_time']
  distance = run_data['summary']['distance_km']
  duration = run_data['summary']['duration']
  pace = run_data['summary']['avg_pace']
  kcals = run_data['summary']['calories_kcal']
  print("Printing values from run data")
  print(date_str)
  print(distance)
  print(duration)
  print(pace)
  print(kcals)
  
  # ==== 3. route ====
  route_x = [0, 1, 2, 3, 4, 5, 6]
  route_y = [0, 1, 0.5, 1.5, 1, 2, 1.5]
  
  plt.figure(figsize=(2,2))
  plt.plot(route_x, route_y, color="white", linewidth=3)
  plt.axis("off")
  
  buf = io.BytesIO()
  plt.savefig(buf, format="PNG", bbox_inches="tight", transparent=True, pad_inches=0.05)
  plt.close()
  buf.seek(0)
  route_img = Image.open(buf).convert("RGBA")
  
  # transparency + scale 
  scale = 0.8
  rw, rh = route_img.size
  route_img = route_img.resize((int(rw*scale), int(rh*scale)))
  alpha = route_img.split()[3]
  alpha = ImageEnhance.Brightness(alpha).enhance(0.4)
  route_img.putalpha(alpha)
  bg.paste(route_img, ((W-route_img.size[0])//2, H-route_img.size[1]-60), route_img)
  
  # ==== 4. fonts ====
  def get_font(preferred_fonts, size):
      for f in preferred_fonts:
          try:
              return ImageFont.truetype(f, size)
          except OSError:
              continue
      return ImageFont.load_default()
  
  preferred_fonts = [
      "/System/Library/Fonts/Supplemental/Helvetica.ttc",  # macOS
      "C:/Windows/Fonts/arial.ttf",                       # Windows
      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
      "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf"
  ]
  
  font_big   = get_font(preferred_fonts, 140)
  font_km    = get_font(preferred_fonts, 50)
  font_small = get_font(preferred_fonts, 42)
  font_label = get_font(preferred_fonts, 28)
  font_date  = get_font(preferred_fonts, 45)
  
  draw = ImageDraw.Draw(bg)
  
  # ==== 5. add text ====
  
  # date
  #tw, th = draw.textsize(date_str, font=font_date)
  left, top, right, bottom = draw.textbbox((0,0), date_str, font=font_date)
  tw, th = right, bottom
  draw.text(((W-tw)//2, 100), date_str, font=font_date, fill=(200,200,200,255))
  
  # distance + KM
  #tw, th = draw.textsize(distance, font=font_big)
  left, top, right, bottom = draw.textbbox((0,0), distance, font=font_big)
  tw, th = right, bottom
  x = (W - tw) // 2
  y = H//3
  draw.text((x, y), distance, font=font_big, fill=(255,255,255,255))
  
  #tw_km, th_km = draw.textsize("KM", font=font_km)
  left, top, right, bottom = draw.textbbox((0,0), "KM", font=font_km)
  tw, th = right, bottom
  draw.text((x + tw + 15, y + 40), "KM", font=font_km, fill=(255,255,255,255))
  
  #  (TIME / PACE / KCALS)
  labels = ["TIME", "PACE", "kCALS"]
  values = [duration, pace, kcals]
  spacing = W // 3
  
  for i, (label, value) in enumerate(zip(labels, values)):
      # 
      #tw, th = draw.textsize(label, font=font_label)
      left, top, right, bottom = draw.textbbox((0,0), label, font=font_label)
      tw, th = right, bottom
      xpos = spacing*i + (spacing - tw)//2
      ypos = H//3 + 200
      draw.text((xpos, ypos), label, font=font_label, fill=(180,180,180,255))
  
      #
      #tw, th = draw.textsize(value, font=font_small)
      left, top, right, bottom = draw.textbbox((0,0), value, font=font_small)
      tw, th = right, bottom
      xpos = spacing*i + (spacing - tw)//2
      ypos = H//3 + 240
      draw.text((xpos, ypos), value, font=font_small, fill=(240,240,240,255))
  
  # ==== 6. save ====
  bg.save(save_img_file)

def main():
    runs_file = os.path.join(parent, "src", "static", "all.json")
    pb_file = os.path.join(parent, "src", "static", "pb.json")
    events_file = os.path.join(parent, "src", "static", "events.json")
    template_file = "template.html"
    output_file = os.path.join(parent, "public", "fun.html")
    bg_file = os.path.join(parent, "public", "images", "sharecardbg.png")
    sharecard_file = os.path.join(parent, "public", "images", "card.png")

    setup_locale()

    all_runs, fastest_run = load_run_data(runs_file)
    if not all_runs:
        print("No run data found. Aborting.")
        return
    long_runs = [run for run in all_runs if run['distance'] > 1000]
    recent_run = long_runs[-1]
    recent_run_json = os.path.join(parent, "public", "data", "details", str(recent_run['id']) + ".json")
    try:
        with open(recent_run_json, 'r', encoding='utf-8') as f:
            recent_run_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: failed to find run file {path}")
        recent_run_data = {}
    if(recent_run_data):
      generate_share_card(bg_file, recent_run_data, sharecard_file)
  
    context = prepare_template_context(all_runs, fastest_run, pb_file, events_file)

    env = Environment(loader=FileSystemLoader(os.path.join(current, '..', 'src', 'static')), autoescape=True)
    env.globals['format_duration'] = format_duration
    
    try:
        template = env.get_template(template_file)
    except Exception as e:
        print(f"Error loading template '{template_file}': {e}")
        return
        
    html_output = template.render(context)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    print(f"Successfully generated report: '{output_file}'")

if __name__ == "__main__":
    parent = os.path.dirname(current) 
    main()












