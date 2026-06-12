import json
import os
from datetime import datetime, timedelta, timezone
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
data_dir = os.path.join(parent, "public", "data")
runs_file = os.path.join(data_dir, "all.json")
runs_details_dir = os.path.join(data_dir, "details")
coros_data_dir = os.path.join(data_dir, "coros_details")
coros_data = os.path.join(coros_data_dir, "data.json")
summary_dir = os.path.join(data_dir, "ai_summary")

UTC8 = timezone(timedelta(hours=8))

def now_utc8():
    return datetime.now(UTC8)

def format_pace(speed_m_s):
    if not speed_m_s or speed_m_s <= 0:
        return "0:00"
    seconds_per_km = 1000 / speed_m_s
    mins = int(seconds_per_km // 60)
    secs = int(seconds_per_km % 60)
    return f"{mins}:{secs:02d}"
def parse_duration_to_seconds(duration_str):
    """
    0:57:16.730000
    """
    parts = duration_str.split(":")
    h = int(parts[0])
    m = int(parts[1])

    sec = float(parts[2])

    return h * 3600 + m * 60 + sec

def get_4weeks_start_date():

    today = now_utc8().date()

    this_monday = today - timedelta(
        days=today.weekday()
    )

    return this_monday - timedelta(weeks=3)
    
def load_recent_runs():
    start_date = get_4weeks_start_date()

    with open(runs_file, "r", encoding="utf-8") as f:
        runs = json.load(f)

    result = []

    for run in runs:

        run_date = datetime.strptime(
            run["start_date_local"],
            "%Y-%m-%d %H:%M:%S"
        ).date()

        if run_date < start_date:
            continue

        result.append({
            "run_id": run["run_id"],
            "distance": run["distance"],
            "moving_time": run["moving_time"],
            "start_date_local": run["start_date_local"],
            "average_heartrate": run.get("average_heartrate"),
            "average_speed": run.get("average_speed")
        })

    result.sort(
        key=lambda x: datetime.strptime(
            x["start_date_local"],
            "%Y-%m-%d %H:%M:%S"
        )
    )

    return result    

def build_weekly_summary(run_logs):

    weekly = {}

    for run in run_logs:

        dt = datetime.strptime(
            run["start_date_local"],
            "%Y-%m-%d %H:%M:%S"
        )

        week_start = (
            dt.date() -
            timedelta(days=dt.weekday())
        )

        key = week_start.strftime("%Y-%m-%d")

        duration_sec = parse_duration_to_seconds(
            run["moving_time"]
        )

        distance = run["distance"]

        avg_hr = run.get("average_heartrate") or 0

        if key not in weekly:
            weekly[key] = {
                "week_start": key,
                "total_distance": 0,
                "total_time": 0,
                "total_heartbeats": 0
            }

        weekly[key]["total_distance"] += distance

        weekly[key]["total_time"] += duration_sec

        weekly[key]["total_heartbeats"] += (
            avg_hr * duration_sec
        )

    result = []

    for item in weekly.values():

        total_time = item["total_time"]

        avg_hr = (
            item["total_heartbeats"] / total_time
            if total_time
            else 0
        )

        avg_speed = (
            item["total_distance"] / total_time
            if total_time
            else 0
        )

        result.append({
            "week_start": item["week_start"],
            "total_distance": round(
                item["total_distance"] / 1000,
                2
            ),
            "average_heartrate": round(avg_hr, 1),
            "average_speed": round(avg_speed, 3),
            "average_pace": format_pace(avg_speed)
        })

    result.sort(
        key=lambda x: x["week_start"]
    )

    return result
    
def build_weekly_summary(run_logs):

    weekly = {}

    for run in run_logs:

        dt = datetime.strptime(
            run["start_date_local"],
            "%Y-%m-%d %H:%M:%S"
        )

        week_start = (
            dt.date() -
            timedelta(days=dt.weekday())
        )

        key = week_start.strftime("%Y-%m-%d")

        duration_sec = parse_duration_to_seconds(
            run["moving_time"]
        )

        distance = run["distance"]

        avg_hr = run.get("average_heartrate") or 0

        if key not in weekly:
            weekly[key] = {
                "week_start": key,
                "total_distance": 0,
                "total_time": 0,
                "total_heartbeats": 0
            }

        weekly[key]["total_distance"] += distance

        weekly[key]["total_time"] += duration_sec

        weekly[key]["total_heartbeats"] += (
            avg_hr * duration_sec
        )

    result = []

    for item in weekly.values():

        total_time = item["total_time"]

        avg_hr = (
            item["total_heartbeats"] / total_time
            if total_time
            else 0
        )

        avg_speed = (
            item["total_distance"] / total_time
            if total_time
            else 0
        )

        result.append({
            "week_start": item["week_start"],
            "total_distance": round(
                item["total_distance"] / 1000,
                2
            ),
            "average_heartrate": round(avg_hr, 1),
            "average_speed": round(avg_speed, 3),
            "average_pace": format_pace(avg_speed)
        })

    result.sort(
        key=lambda x: x["week_start"],
        reverse=True
    )

    return result
    
def load_current_week_run_details(run_logs):

    this_monday = (
        now_utc8().date()
        - timedelta(days=now_utc8().weekday())
    )

    run_ids = []

    for run in run_logs:

        run_date = datetime.strptime(
            run["start_date_local"],
            "%Y-%m-%d %H:%M:%S"
        ).date()

        week_start = run_date - timedelta(
            days=run_date.weekday()
        )

        if week_start == this_monday:
            run_ids.append(run["run_id"])

    details = []

    for run_id in run_ids:

        detail_file = os.path.join(
            runs_details_dir,
            f"{run_id}.json"
        )

        if not os.path.exists(detail_file):
            continue

        with open(
            detail_file,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        start_time = data.get("start_time")

        weekday_name = None

        if start_time:
            dt = datetime.fromisoformat(
                start_time.replace("Z", "+00:00")
            )

            weekday_name = [
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
                "Sun"
            ][dt.astimezone(UTC8).weekday()]
        start_dt = datetime.fromisoformat(
            start_time.replace("Z", "+00:00")
        )

        start_dt_utc8 = start_dt.astimezone(
            UTC8
        )

        local_start_time = start_dt_utc8.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        details.append({
            "run_id": run_id,
            "start_time": start_time,
            "start_time_local": local_start_time,
            "weekday": weekday_name,
            "summary": data.get("summary"),
            "laps": data.get("laps", [])
        })
    details.sort(
        key=lambda x: x["start_time"]
    )
    return details
    
def load_last_summary_focus():

    index_file = os.path.join(
        summary_dir,
        "index.json"
    )

    if not os.path.exists(index_file):
        return ""

    with open(
        index_file,
        "r",
        encoding="utf-8"
    ) as f:
        index_data = json.load(f)

    if not index_data:
        return ""

    filename = index_data[0]["filename"]

    md_file = os.path.join(
        summary_dir,
        filename
    )

    if not os.path.exists(md_file):
        return ""

    with open(
        md_file,
        "r",
        encoding="utf-8"
    ) as f:
        content = f.read()

    start_tag = "### 四、 下一阶段"

    pos = content.find(start_tag)

    if pos == -1:
        return ""

    return content[pos:].strip()
    
def extract_coros_data(data_path):
    """提取 COROS EvoLab 生理基线和近期疲劳数据"""
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            d1 = json.load(f).get('data', {}).get('dayList', [])
            
        latest_state = d1[-1] if d1 else {}

        return {
            "physiological_baseline": {
                "vo2max": latest_state.get('vo2max', 53),
                "lthr_bpm": latest_state.get('lthr', 161),
                "ltsp_pace": "4:24",
                "recent_rhr": latest_state.get('rhr'),
                "recent_sleep_hrv": latest_state.get('avgSleepHrv')
            },
            "current_load_status": {
                "7d_training_load": latest_state.get('t7d'),
                "28d_training_load": latest_state.get('t28d'),
                "stamina_level": latest_state.get('staminaLevel'),
                "fatigue_rate": latest_state.get('tiredRate')
            }
        }
    except Exception as e:
        print(f"解析 COROS 数据失败: {e}")
        return {}

def generate_ai_report(ai_context_json):
    
    prompt = f"""
    【角色设定】
    你现在是一位具备运动生理学背景的精英马拉松教练，擅长通过数据分析进行科学的周期化训练安排。

    【背景与目标】
    1. 当前水平：全马 PB 为 3:53:07。
    2. 未来目标：参加 2026 年 12 月底的广州马拉松，目标成绩 3:30 至 3:45。
    3. 训练设备：COROS 手表。

    【我的数据】
    以下是我近期从 COROS EvoLab 导出的生理基线数据、疲劳负荷状态，以及最近 4 周的详细跑步流水记录：
    {json.dumps(ai_context_json, indent=2, ensure_ascii=False)}

    【请你执行以下分析与指导】
    1. 结合上一次训练报告中的“下一阶段重点”（weekly_training_advice），评估本周训练执行情况。
    2. 基于 VO2Max、LTHR、训练负荷、疲劳指数和近期跑量，评估目前是否具备在 2026 广州马拉松实现3:30~3:45 完赛目标的能力。
    3. 近期训练诊断：
        分析最近4周训练情况：

        - 周跑量变化趋势
        - 有氧跑占比是否合理
        - 轻松跑心率控制是否合理
        - 是否存在垃圾跑量
        - 是否存在恢复不足
    4. 本周训练复盘：
        结合每次跑步的 laps 数据，
        分析配速控制、心率漂移、
        有氧效率和节奏跑执行质量。
    5. 下一阶段重点：
        未来4周基础期训练，
        应该优先：

        A. 增加周跑量

        还是

        B. 提升跑动经济性

        请说明原因。

        并给出：

        - 每周目标跑量
        - 每周训练结构
        - 长距离安排
        - 节奏跑安排
        - 恢复跑安排

        6. 最后输出：

        【一句话总结】
        【本周评分（100分）】
        【最大优点】
        【最大短板】
        【下周最重要的一件事】

    请用专业、中肯且直白的语言回答，直接指出训练短板，使用 Markdown 格式排版，不要加多余的客套话。
    """
    
    print("正在请求 Gemini API，请稍候...")
    
    try:
        #response = client.models.generate_content(
        #    model='gemini-3.5-flash',
        #    contents=prompt
        #)
        #return response.text
        return None
    except Exception as e:
        print(f"调用 Gemini API 失败: {e}")
        return None

def update_ai_index(target_dir):
    """扫描报告目录并生成带有时间排序的 index.json，供前端读取"""
    if not os.path.exists(target_dir):
        return
        
    md_files = [f for f in os.listdir(target_dir) if f.endswith('_ai_summary.md')]
    index_data = []
    
    for filename in md_files:
        # 文件名格式约束为 "YYYY-MM-DD_ai_summary.md"
        date_str = filename.split('_')[0]
        index_data.append({
            "date": date_str,
            "filename": filename
        })
        
    # 按时间降序排序（最新的在前面）
    index_data.sort(key=lambda x: x['date'], reverse=True)
    
    index_path = os.path.join(target_dir, "index.json")
    try:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        print(f"✅ AI 报告索引已更新，共 {len(index_data)} 份报告。")
    except Exception as e:
        print(f"❌ 更新 AI 索引失败: {e}")

# ==========================================
# 4. 主流程与文件保存
# ==========================================
def main():
    #if now_utc8().weekday() != 6:
    #    return
    print("开始提取数据...")

    recent_runs = load_recent_runs()

    weekly_summary = build_weekly_summary(
        recent_runs
    )

    current_week_run_details = load_current_week_run_details(
        recent_runs
    )

    coros_summary = extract_coros_data(
        coros_data
    )

    last_summary_focus = load_last_summary_focus()

    ai_context = {
        "weekly_training_advice": last_summary_focus,
        "current_week_runs": current_week_run_details,
        "recent_4_weeks_runs": recent_runs,
        "recent_4_weeks_summary": weekly_summary,
        "athlete_profile": coros_summary
    }
    print("提取到的信息如下:")
    print(json.dumps(ai_context, indent=4))    
    # 获取 AI 报告
    report_content = generate_ai_report(ai_context)

    if report_content:
        # 以当天日期命名文件
        date_str = now_utc8().strftime("%Y-%m-%d")
        filename = os.path.join(summary_dir, f"{date_str}_ai_summary.md")
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        # 写入 Markdown 文件
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {date_str} 周期训练分析报告\n\n")
            f.write(report_content)
            
        print(f"✅ 成功！报告已保存至: {filename}")
        
        # 更新供前端调用的索引文件
        update_ai_index(summary_dir)
    else:
        print("❌ 报告生成失败。")

if __name__ == "__main__":
    main()
