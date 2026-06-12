import json
import os
from datetime import datetime, timedelta, timezone
from google import genai
from google.genai import types

# ==========================================
# 1. 基础配置与路径设置
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
data_dir = os.path.join(parent, "public", "data")
runs_file = os.path.join(data_dir, "all.json")
runs_details_dir = os.path.join(data_dir, "details")

# 新的目录结构规划
summary_dir = os.path.join(data_dir, "summary")
reports_dir = os.path.join(summary_dir, "reports")
plans_dir = os.path.join(summary_dir, "plans")
reviews_dir = os.path.join(summary_dir, "reviews")

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
    parts = duration_str.split(":")
    h = int(parts[0])
    m = int(parts[1])
    sec = float(parts[2])
    return h * 3600 + m * 60 + sec

def get_4weeks_start_date():
    today = now_utc8().date()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(weeks=3)

# ==========================================
# 2. 数据处理与提取
# ==========================================
def load_recent_runs():
    start_date = get_4weeks_start_date()
    
    if not os.path.exists(runs_file):
        return []

    with open(runs_file, "r", encoding="utf-8") as f:
        runs = json.load(f)

    result = []
    for run in runs:
        run_date = datetime.strptime(run["start_date_local"], "%Y-%m-%d %H:%M:%S").date()
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

    result.sort(key=lambda x: datetime.strptime(x["start_date_local"], "%Y-%m-%d %H:%M:%S"))
    return result    

def build_weekly_summary(run_logs):
    weekly = {}
    for run in run_logs:
        dt = datetime.strptime(run["start_date_local"], "%Y-%m-%d %H:%M:%S")
        week_start = (dt.date() - timedelta(days=dt.weekday()))
        key = week_start.strftime("%Y-%m-%d")
        
        duration_sec = parse_duration_to_seconds(run["moving_time"])
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
        weekly[key]["total_heartbeats"] += (avg_hr * duration_sec)

    result = []
    for item in weekly.values():
        total_time = item["total_time"]
        avg_hr = item["total_heartbeats"] / total_time if total_time else 0
        avg_speed = item["total_distance"] / total_time if total_time else 0

        result.append({
            "week_start": item["week_start"],
            "total_distance": round(item["total_distance"] / 1000, 2),
            "average_heartrate": round(avg_hr, 1),
            "average_speed": round(avg_speed, 3),
            "average_pace": format_pace(avg_speed)
        })

    result.sort(key=lambda x: x["week_start"], reverse=True)
    return result

def load_current_week_run_details(run_logs):
    this_monday = (now_utc8().date() - timedelta(days=now_utc8().weekday()))
    run_ids = []

    for run in run_logs:
        run_date = datetime.strptime(run["start_date_local"], "%Y-%m-%d %H:%M:%S").date()
        week_start = run_date - timedelta(days=run_date.weekday())
        if week_start == this_monday:
            run_ids.append(run["run_id"])

    details = []
    for run_id in run_ids:
        detail_file = os.path.join(runs_details_dir, f"{run_id}.json")
        if not os.path.exists(detail_file):
            continue

        with open(detail_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        start_time = data.get("start_time")
        weekday_name = None
        local_start_time = None

        if start_time:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            weekday_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.astimezone(UTC8).weekday()]
            start_dt_utc8 = dt.astimezone(UTC8)
            local_start_time = start_dt_utc8.strftime("%Y-%m-%d %H:%M:%S")

        details.append({
            "run_id": run_id,
            "start_time": start_time,
            "start_time_local": local_start_time,
            "weekday": weekday_name,
            "summary": data.get("summary"),
            "laps": data.get("laps", [])
        })

    details.sort(key=lambda x: x["start_time"])
    return details

# ==========================================
# 3. 闭环核心逻辑：计划抓取与执行率计算
# ==========================================
def load_last_week_plan():
    """读取上周生成的 JSON 训练计划"""
    if not os.path.exists(plans_dir):
        return None
        
    plan_files = [f for f in os.listdir(plans_dir) if f.endswith('.json')]
    if not plan_files:
        return None
        
    # 按日期倒序，取最新的一份计划
    plan_files.sort(reverse=True)
    latest_plan_file = os.path.join(plans_dir, plan_files[0])
    
    with open(latest_plan_file, "r", encoding="utf-8") as f:
        return json.load(f)

def evaluate_plan_completion(plan, current_week_runs, weekly_summary):
    """客观计算计划的完成度，直接投喂给 Gemini"""
    if not plan:
        return None

    planned_sessions = len(plan.get("sessions", []))
    completed_sessions = len(current_week_runs)
    distance_target = plan.get("target_distance_km", 0)
    
    # 从本周汇总数据中抓取本周实际总跑量
    this_monday = (now_utc8().date() - timedelta(days=now_utc8().weekday())).strftime("%Y-%m-%d")
    distance_actual = 0
    for week in weekly_summary:
        if week["week_start"] == this_monday:
            distance_actual = week["total_distance"]
            break

    completion_rate = round((completed_sessions / planned_sessions) * 100) if planned_sessions > 0 else 0
    distance_completion = round((distance_actual / distance_target) * 100) if distance_target > 0 else 0

    return {
        "completion_rate": completion_rate,
        "planned_sessions": planned_sessions,
        "completed_sessions": completed_sessions,
        "distance_target": distance_target,
        "distance_actual": round(distance_actual, 2),
        "distance_completion": distance_completion
    }

# ==========================================
# 4. AI 报告生成与结构化处理
# ==========================================
def generate_ai_report(ai_context_dict):
    """使用 Structured Outputs 强制 Gemini 返回指定 JSON 格式"""
    
    # 强制返回格式 Schema 定义
    response_schema = {
        "type": "OBJECT",
        "properties": {
            "human_report_md": {"type": "STRING"},
            "execution_review": {
                "type": "OBJECT",
                "properties": {
                    "completion_rate": {"type": "NUMBER"},
                    "overall_score": {"type": "NUMBER"},
                    "strength": {"type": "STRING"},
                    "weakness": {"type": "STRING"},
                    "next_focus": {"type": "STRING"}
                }
            },
            "next_week_plan": {
                "type": "OBJECT",
                "properties": {
                    "week_start": {"type": "STRING"},
                    "phase": {"type": "STRING"},
                    "goal": {"type": "STRING"},
                    "target_distance_km": {"type": "NUMBER"},
                    "target_training_load": {"type": "NUMBER"},
                    "sessions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "id": {"type": "STRING"},
                                "day": {"type": "STRING"},
                                "type": {"type": "STRING"},
                                "distance_km": {"type": "NUMBER"},
                                "target_hr_max": {"type": "NUMBER"},
                                "notes": {"type": "STRING"},
                                "warmup_km": {"type": "NUMBER"},
                                "main_set": {"type": "STRING"},
                                "target_pace": {"type": "STRING"},
                                "cooldown_km": {"type": "NUMBER"}
                            }
                        }
                    }
                }
            }
        },
        "required": ["human_report_md", "execution_review", "next_week_plan"]
    }

    prompt = f"""
你是一名马拉松教练。

你的任务：
1. 对比上周计划与本周实际训练
2. 分析下面提供的客观评估完成度指标（解释为什么是这个完成率，分析原因）
3. 分析近4周趋势
4. 调整并输出下周训练计划 (next_week_plan)
5. 输出人类可读报告，且报告最后加入人类可读的下周训练计划 (human_report_md)

以下是运行数据和评估环境上下文（JSON格式）：
{json.dumps(ai_context_dict, ensure_ascii=False, indent=2)}

严格按照要求的 JSON 格式返回，不要包含任何额外的 Markdown 标记（例如 ```json）和无关文本。
"""

    print("正在请求 Gemini API，请稍候...")
    try:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.7
        )
        
        response = client.models.generate_content(
            model='gemini-3.5-flash', # 请根据你实际的模型名称调整
            contents=prompt,
            config=config
        )
        
        # 将大模型返回的 JSON 字符串解析为 Python 字典
        return json.loads(response.text)
    except Exception as e:
        print(f"调用 Gemini API 失败或解析结果失败: {e}")
        return None

def update_ai_index():
    """扫描 reports 目录并生成 index.json"""
    if not os.path.exists(reports_dir):
        return
        
    md_files = [f for f in os.listdir(reports_dir) if f.endswith('.md')]
    index_data = []
    
    for filename in md_files:
        date_str = filename.replace('.md', '')
        index_data.append({
            "date": date_str,
            "report": f"reports/{date_str}.md",
            "plan": f"plans/{date_str}.json",
            "review": f"reviews/{date_str}.json"
        })
        
    index_data.sort(key=lambda x: x['date'], reverse=True)
    index_path = os.path.join(summary_dir, "index.json")
    
    try:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        print(f"✅ AI 报告索引已更新，共 {len(index_data)} 份记录。")
    except Exception as e:
        print(f"❌ 更新 AI 索引失败: {e}")

# ==========================================
# 5. 主流程控制
# ==========================================
def main():
    #if now_utc8().weekday() != 6:
    #    return
    print("创建所需目录体系...")
    for directory in [reports_dir, plans_dir, reviews_dir]:
        os.makedirs(directory, exist_ok=True)

    print("开始提取数据...")
    recent_runs = load_recent_runs()
    weekly_summary = build_weekly_summary(recent_runs)
    current_week_run_details = load_current_week_run_details(recent_runs)
    
    last_week_plan = load_last_week_plan()
    execution_stats = evaluate_plan_completion(last_week_plan, current_week_run_details, weekly_summary)

    ai_context = {
        "recent_4_weeks_summary": weekly_summary,
        "recent_4_weeks_runs": recent_runs,
        "current_week_runs": current_week_run_details,
        "last_week_plan": last_week_plan,
        "execution_stats": execution_stats
    }
    
    print("提取到的信息摘要:")
    print(f"- 本周课时数: {len(current_week_run_details)}")
    if execution_stats:
        print(f"- 上周计划完成度: {execution_stats['completion_rate']}%")
    print("所有信息:")
    print(json.dumps(ai_context, indent=4))
    ai_result_dict = generate_ai_report(ai_context)
    ai_result_dict = None
    if ai_result_dict:
        date_str = now_utc8().strftime("%Y-%m-%d")
        
        # 1. 保存供人看的 Markdown 报告
        report_path = os.path.join(reports_dir, f"{date_str}.md")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# {date_str} 周期训练分析报告\n\n")
            f.write(ai_result_dict.get("human_report_md", "报告内容为空。"))
            
        # 2. 保存下周计划 JSON
        plan_path = os.path.join(plans_dir, f"{date_str}.json")
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(ai_result_dict.get("next_week_plan", {}), f, ensure_ascii=False, indent=2)
            
        # 3. 保存本周执行度 Review JSON
        review_path = os.path.join(reviews_dir, f"{date_str}.json")
        with open(review_path, 'w', encoding='utf-8') as f:
            json.dump(ai_result_dict.get("execution_review", {}), f, ensure_ascii=False, indent=2)
            
        print(f"✅ 成功！报告、计划和复盘均已保存（日期：{date_str}）。")
        
        # 更新总目录的 index.json
        update_ai_index()
    else:
        print("❌ 报告生成失败。")

if __name__ == "__main__":
    main()
