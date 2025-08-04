import json
from datetime import datetime, timedelta, date
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
import sys
import locale
import os
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
# --- Configuration ---
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
    "city_coordinates": {
		# 直辖市
		'北京市': [39.904, 116.407],
		'上海市': [31.230, 121.473],
		'天津市': [39.084, 117.201],
		'重庆市': [29.563, 106.551],
		
		# 广东省
		'广州市': [23.129, 113.264],
		'深圳市': [22.543, 114.058],
		'珠海市': [22.271, 113.576],
		'佛山市': [23.022, 113.122],
		'东莞市': [23.020, 113.751],
		'中山市': [22.517, 113.392],
		'惠州市': [23.112, 114.416],
		'清远市': [23.682, 113.056],
		'茂名市': [21.663, 110.925],
		
		# 其他省会/重点城市
		'成都市': [30.572, 104.066],
		'杭州市': [30.274, 120.155],
		'武汉市': [30.593, 114.305],
		'南京市': [32.060, 118.797],
		'西安市': [34.341, 108.940],
		'长沙市': [28.228, 112.938],
		'苏州市': [31.299, 120.585],
		'厦门市': [24.480, 118.089],
		'青岛市': [36.067, 120.382],
		'大连市': [38.914, 121.615],
		
		# 东北地区
		'沈阳市': [41.803, 123.425],
		'长春市': [43.817, 125.324],
		'哈尔滨市': [45.803, 126.535],
		
		# 西北地区
		'乌鲁木齐市': [43.825, 87.617],
		'银川市': [38.487, 106.230],
		'兰州市': [36.061, 103.834],
		
		# 西南地区
		'昆明市': [25.043, 102.832],
		'贵阳市': [26.647, 106.630],
		'拉萨市': [29.646, 91.117],
		
		# 港澳台
		'香港': [22.319, 114.169],
		'澳门': [22.179, 113.549],
		'台北市': [25.033, 121.565]
    }
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

def prepare_template_context(all_runs, fastest_run, pb_file, events_file):
    if not all_runs:
        return {}

    events = load_events_data(events_file)
    
    # --- Get recent 3 runs for display ---
    recent_runs = list(reversed(all_runs[-3:]))
    
    # --- City Statistics (from all runs) ---
    city_stats_agg = defaultdict(lambda: {'count': 0, 'distance': 0.0})
    for run in all_runs:
        city = run['city']
        if city and city != '未知':
            city_stats_agg[city]['count'] += 1
            city_stats_agg[city]['distance'] += run['distance'] / 1000

    city_stats = [
        {'name': city, 'count': data['count'], 'distance': round(data['distance'], 2), 
         'coordinates': CONFIG["city_coordinates"].get(city, [])}
        for city, data in city_stats_agg.items()
    ]
    city_stats.sort(key=lambda x: (x['count'], x['distance']), reverse=True)

    # --- Chart: Last 30 Days ---
    today = datetime.now().date()
    thirty_days_ago = today - timedelta(days=29)
    last_30_days_data = { (thirty_days_ago + timedelta(days=i)): 0.0 for i in range(30) }
    
    recent_runs_30_days = [r for r in all_runs if r['date'].date() >= thirty_days_ago]
    for run in recent_runs_30_days:
        run_date = run['date'].date()
        if run_date in last_30_days_data:
            last_30_days_data[run_date] += run['distance'] / 1000
            
    chart_30_days_labels = [d.strftime('%m-%d') for d in sorted(last_30_days_data.keys())]
    chart_30_days_values = [round(last_30_days_data[d], 2) for d in sorted(last_30_days_data.keys())]
    
    chart_30_days = {'labels': chart_30_days_labels, 'data': chart_30_days_values}

    # --- Other Statistics ---
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
        summarized_by_year[year] = {"summary": summarize_runs(year_runs), "months": {}}
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

    # --- Yearly Chart Data ---
    years_for_chart = sorted(summarized_by_year.keys())
    chart_yearly_labels = [str(y) for y in years_for_chart]
    chart_yearly_data = [round(summarized_by_year[y]["summary"]["dist_km"], 2) for y in years_for_chart]

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
    }

def main():
    runs_file = os.path.join(parent, "src", "static", "all.json")
    pb_file = os.path.join(parent, "src", "static", "pb.json")
    events_file = os.path.join(parent, "src", "static", "events.json")
    template_file = "template.html"
    output_file = os.path.join(parent, "public", "fun.html")

    setup_locale()

    all_runs, fastest_run = load_run_data(runs_file)
    if not all_runs:
        print("No run data found. Aborting.")
        return

    context = prepare_template_context(all_runs, fastest_run, pb_file, events_file)

    env = Environment(loader=FileSystemLoader('src/static'), autoescape=True)
    env.globals['format_duration'] = format_duration
    
    try:
        template = env.get_template(template_file)
    except Exception as e:
        print(f"Error loading template '{template_file}': {e}")
        return
        
    html_output = template.render(context)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    print(f"Successfully generated report: '{output_file}'")

if __name__ == "__main__":
    main()
