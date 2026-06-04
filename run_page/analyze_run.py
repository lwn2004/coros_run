import os
import json
import re
from datetime import datetime, timedelta, timezone
import google.generativeai as genai

# ==========================================
# 1. 初始化路径
# ==========================================
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)

runs_file = os.path.join(parent, "src", "static", "all.json")
data_dir = os.path.join(parent, "public", "data")
details_dir = os.path.join(data_dir, "details")
summary_dir = os.path.join(data_dir, "ai_summary")
summary_file = os.path.join(summary_dir, "last_run_summary.md")

# ==========================================
# 2. Gemini API 配置
# ==========================================
# 请确保你的环境变量中设置了 GEMINI_API_KEY，或在此处直接填入字符串
API_KEY = os.environ.get("GEMINI_API_KEY") 
if not API_KEY:
    raise ValueError("未找到 GEMINI_API_KEY，请设置环境变量。")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-3.1-pro')

# ==========================================
# 3. 辅助计算函数
# ==========================================
def parse_moving_time(time_str):
    """将 moving_time (如 '0:40:07.120000') 转换为秒数"""
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def format_pace(seconds_per_km):
    """将秒/公里转换为配速格式 (如 5'43\")"""
    if seconds_per_km <= 0: return "0'00\""
    m = int(seconds_per_km // 60)
    s = int(seconds_per_km % 60)
    return f"{m}'{s:02d}\""

# ==========================================
# 4. 主逻辑执行
# ==========================================
def main():
    # --- A. 读取并解析 all.json 找出最新日期 ---
    with open(runs_file, 'r', encoding='utf-8') as f:
        all_runs = json.load(f)

    if not all_runs:
        print("未在 all.json 中找到跑步记录。")
        return

    # 确保按时间降序排列，取最新一条记录
    all_runs.sort(key=lambda x: x["start_date_local"], reverse=True)
    latest_run = all_runs[0]
    
    # 提取纯日期部分，例如 "2026-06-04"
    latest_date_str = latest_run["start_date_local"].split(" ")[0]
    ref_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()
    print(f"🎯 锁定最新跑步日期: {latest_date_str}")

    # --- B. 获取【数据1】：当天的所有详细数据 ---
    latest_day_runs = [r for r in all_runs if r["start_date_local"].startswith(latest_date_str)]
    data_1_latest_details = []
    keys_to_extract = ["run_id", "start_time", "weather", "summary", "laps"]

    for r in latest_day_runs:
        run_id = r["run_id"]
        detail_path = os.path.join(details_dir, f"{run_id}.json")
        if os.path.exists(detail_path):
            with open(detail_path, 'r', encoding='utf-8') as df:
                detail_data = json.load(df)
                # 1. 仅提取需要的 key
                extracted = {k: detail_data.get(k) for k in keys_to_extract if k in detail_data}
                
                # 2. 针对 start_time 进行加 8 小时兼容处理
                if "start_time" in extracted and extracted["start_time"]:
                    try:
                        # fromisoformat 可以无缝解析 "2026-05-26T21:54:04" 或 "2026-05-26 21:54:04"
                        dt = datetime.fromisoformat(extracted["start_time"])
                        
                        if dt.tzinfo is None:
                            # 【场景 A】如果没有时区信息，说明是 naive time
                            # 默认把它当作 UTC 时间，先补上 UTC 时区，再转成东八区（此时末尾会自动带上 +08:00）
                            dt_utc = dt.replace(tzinfo=timezone.utc)
                            dt_local = dt_utc.astimezone(timezone(timedelta(hours=8)))
                            
                            # 如果你【不想要】末尾带上 "+08:00" 后缀，只要干净的 local 时间字符串，请取消注释下面这行：
                            # dt_local = dt + timedelta(hours=8)
                        else:
                            # 【场景 B】如果原本就带有群组时区（如 +00:00）
                            dt_local = dt.astimezone(timezone(timedelta(hours=8)))
                        
                        extracted["start_time"] = dt_local.isoformat()
                        
                    except Exception as e:
                        print(f"解析或转换 start_time 失败 (run_id: {run_id}): {e}")

                data_1_latest_details.append(extracted)
    # --- C. 获取【数据2】：周/月/年的周期性统计 ---
    stats = {
        "week": {"dist_km": 0, "time_sec": 0, "hr_x_time": 0},
        "month": {"dist_km": 0, "time_sec": 0, "hr_x_time": 0},
        "year": {"dist_km": 0, "time_sec": 0, "hr_x_time": 0},
    }

    # 使用 ISO 标准来判定是否为同一年/同一周
    ref_year, ref_week, _ = ref_date.isocalendar()
    ref_month = ref_date.month

    for r in all_runs:
        if not r.get("start_date_local") or "moving_time" not in r:
            continue

        run_date_obj = datetime.strptime(r["start_date_local"].split(" ")[0], "%Y-%m-%d").date()
        r_year, r_week, _ = run_date_obj.isocalendar()
        r_month = run_date_obj.month

        dist_km = r.get("distance", 0) / 1000.0
        t_sec = parse_moving_time(r["moving_time"])
        hr = r.get("average_heartrate", 0) or 0

        # 判断并累加（按年份）
        if run_date_obj.year == ref_date.year:
            stats["year"]["dist_km"] += dist_km
            stats["year"]["time_sec"] += t_sec
            if hr > 0: stats["year"]["hr_x_time"] += hr * t_sec

        # 判断并累加（按月份）
        if run_date_obj.year == ref_date.year and r_month == ref_month:
            stats["month"]["dist_km"] += dist_km
            stats["month"]["time_sec"] += t_sec
            if hr > 0: stats["month"]["hr_x_time"] += hr * t_sec

        # 判断并累加（按周）
        if r_year == ref_year and r_week == ref_week:
            stats["week"]["dist_km"] += dist_km
            stats["week"]["time_sec"] += t_sec
            if hr > 0: stats["week"]["hr_x_time"] += hr * t_sec

    # 格式化【数据2】文本
    def format_stat(stat_dict):
        d = stat_dict["dist_km"]
        t = stat_dict["time_sec"]
        hr_total = stat_dict["hr_x_time"]
        
        avg_pace = format_pace(t / d) if d > 0 else "0'00\""
        avg_hr = round(hr_total / t) if t > 0 and hr_total > 0 else 0
        hours, remainder = divmod(t, 3600)
        mins = remainder // 60
        
        return f"跑量: {d:.2f} km, 时间: {int(hours)}小时{int(mins)}分, 平均配速: {avg_pace}, 平均心率: {avg_hr} bpm"

    data_2_stats_str = (
        f"- 本周统计 (第{ref_week}周): {format_stat(stats['week'])}\n"
        f"- 本月统计 ({ref_month}月): {format_stat(stats['month'])}\n"
        f"- 本年统计 ({ref_date.year}年): {format_stat(stats['year'])}"
    )
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)
    # --- D. 处理旧的 recent_run_summary.txt ---
    if os.path.exists(summary_file):
        with open(summary_file, 'r', encoding='utf-8') as f:
            old_content = f.read()

        # 正则匹配寻找旧报告里的日期 (兼容 2026-05-26, 2026/05/26, 2026年5月26日 格式)
        date_pattern = r"(20\d{2})[-年/](1[0-2]|0?[1-9])[-月/](3[01]|[12]\d|0?[1-9])日?"
        match = re.search(date_pattern, old_content)
        
        if match:
            y, m, d = match.groups()
            old_date_str = f"{y}-{int(m):02d}-{int(d):02d}"
        else:
            # 如果文本里没找到，回退到使用文件的修改日期
            mtime = os.path.getmtime(summary_file)
            old_date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

        new_filename = f"last_run_summary_{old_date_str}.md"
        os.rename(summary_file, os.path.join(summary_dir, new_filename))
        print(f"📦 已将旧报告归档为: {new_filename}")

    # --- E. 组装 Prompt 并调用 Gemini ---
    prompt = f"""
你现在是一位严谨且专业的马拉松长跑教练。我将提供我最近一天的跑步数据以及本周、本月、今年的累计跑步统计。
请帮我进行深度复盘，尤其关注长距离耐力积累、配速分布、步频表现和心率控制。

【最新一天跑步数据】
{json.dumps(data_1_latest_details, ensure_ascii=False, indent=2)}

【周期性统计数据】
{data_2_stats_str}

请按以下结构输出总结（请直接使用 Markdown 格式，不要加多余的客套话）：

### 1. 最近一次表现分析(需写出对应的日期)
评估最近一天跑步的质量，点评步频与心率的匹配度，是否有亮点或不足。

### 2. 周期跑量复盘 (周/月/年)
结合我本周、本月和今年的累计跑量，评估我的训练连贯性和跑量积累情况。指出当前的月跑量/年跑量是否处于合理的马拉松训练节奏中。计划在12月份参加马拉松比赛。

### 3. 教练建议与加强方向
给出具体的改进建议。例如：是否需要增加基础有氧（LSD）、是否需要针对心率漂移进行专项训练，或者是否要注意避免过度训练。
"""

    print("🧠 正在请求 Gemini 教练生成复盘报告...")
    response = model.generate_content(prompt)

    # --- F. 保存新的分析报告 ---
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(response.text)

    print(f"✅ 生成完毕！最新报告已保存至: {summary_file}")

if __name__ == "__main__":
    main()
