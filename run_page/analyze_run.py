import json
import os
from datetime import datetime
from google import genai

# ==========================================
# 1. 配置与初始化
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)
current = os.path.dirname(os.path.realpath(__file__))
parent = os.path.dirname(current)
data_dir = os.path.join(parent, "public", "data")
runs_file = os.path.join(data_dir, "all.json")
coros_data_dir = os.path.join(data_dir, "coros_details")
coros_data1 = os.path.join(coros_data_dir, "data1.json")
coros_data2 = os.path.join(coros_data_dir, "data2.json")
summary_dir = os.path.join(data_dir, "ai_summary")

# ==========================================
# 2. 数据解析函数
# ==========================================
def format_pace(speed_m_s):
    """将 m/s 转换为 分:秒/公里 的配速格式"""
    if not speed_m_s or speed_m_s <= 0:
        return "0:00"
    seconds_per_km = 1000 / speed_m_s
    mins = int(seconds_per_km // 60)
    secs = int(seconds_per_km % 60)
    return f"{mins}:{secs:02d}"

def extract_coros_data(data1_path, data3_path):
    """提取 COROS EvoLab 生理基线和近期疲劳数据"""
    try:
        with open(data1_path, 'r', encoding='utf-8') as f:
            d1 = json.load(f).get('data', {}).get('dayList', [])
        with open(data3_path, 'r', encoding='utf-8') as f:
            d3 = json.load(f).get('data', {}).get('summaryInfo', {})
            
        latest_state = d1[-1] if d1 else {}
        
        pbs = d3.get('recordDetailList', [])
        pb_summary = {}
        if len(pbs) > 0 and 'recordList' in pbs[0]:
            for record in pbs[0]['recordList']:
                dist = record.get('distance', 0)
                duration = record.get('duration', 0)
                if dist == 42195: pb_summary['Full_Marathon'] = duration
                elif dist == 21097.5: pb_summary['Half_Marathon'] = duration
                elif dist == 10000: pb_summary['10km'] = duration
                elif dist == 5000: pb_summary['5km'] = duration

        return {
            "physiological_baseline": {
                "vo2max": latest_state.get('vo2max', d3.get('vo2max')),
                "lthr_bpm": d3.get('lthr', latest_state.get('lthr')),
                "ltsp_pace": format_pace(1000 / d3.get('ltsp')) if d3.get('ltsp') else "N/A",
                "recent_rhr": latest_state.get('rhr'),
                "recent_sleep_hrv": latest_state.get('avgSleepHrv')
            },
            "current_load_status": {
                "7d_training_load": latest_state.get('t7d'),
                "28d_training_load": latest_state.get('t28d'),
                "stamina_level": latest_state.get('staminaLevel'),
                "fatigue_rate": latest_state.get('tiredRate')
            },
            "pb_records_seconds": pb_summary
        }
    except Exception as e:
        print(f"解析 COROS 数据失败: {e}")
        return {}

def extract_all_json(all_json_path, days=28):
    """从 all.json 中提取最近跑步流水"""
    try:
        with open(all_json_path, 'r', encoding='utf-8') as f:
            runs = json.load(f)
            
        recent_runs = []
        runs.sort(key=lambda x: x.get('start_date_local', ''), reverse=True)
        
        for run in runs[:days]:
            if run.get('type') == 'Run':
                recent_runs.append({
                    "date": run.get('start_date_local', '').split(' ')[0],
                    "distance_km": round(run.get('distance', 0) / 1000, 2),
                    "moving_time": run.get('moving_time'),
                    "avg_hr": run.get('average_heartrate'),
                    "avg_pace": format_pace(run.get('average_speed', 0))
                })
        return recent_runs
    except Exception as e:
        print(f"解析 all.json 失败: {e}")
        return []

# ==========================================
# 3. 生成 Prompt 并调用 Gemini API
# ==========================================
def generate_ai_report(ai_context_json):
    """将数据发送给 Gemini 并获取报告"""
    
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
    1. 体能状态评估：基于最大摄氧量 (VO2Max)、乳酸阈值心率 (LTHR) 和近期的疲劳/负荷指数，评估目前的有氧基础是否足以支撑广马 3:30-3:45 的目标？
    2. 近期训练诊断：分析最近 4 周的日常跑步数据，轻松跑（有氧底盘）心率控制得合理吗？是否有垃圾跑量？
    3. 训练配速建议：根据 LTHR 和历史表现，精确计算并给出接下来的：轻松跑 (E)、马拉松配速跑 (M)、乳酸阈值跑 (T) 和间歇跑 (I) 的推荐配速区间和心率区间。
    4. 下一阶段重点：在接下来的 4 周基础期内，应该把训练重心放在增加周跑量，还是提升跑动经济性？请给出具体的每周训练结构建议。

    请用专业、中肯且直白的语言回答，直接指出训练短板，使用 Markdown 格式排版，不要加多余的客套话。
    """
    
    print("正在请求 Gemini API，请稍候...")
    
    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt
        )
        return response.text
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
    if datetime.now().weekday() != 6:
        return
    print("开始提取数据...")
    coros_summary = extract_coros_data(coros_data1, coros_data2)
    run_logs = extract_all_json(runs_file, days=28)
    
    if not coros_summary or not run_logs:
        print("警告：部分数据提取失败，请检查 JSON 文件路径和内容。")

    ai_context = {
        "athlete_profile": coros_summary,
        "recent_4_weeks_runs": run_logs
    }

    # 获取 AI 报告
    report_content = generate_ai_report(ai_context)

    if report_content:
        # 以当天日期命名文件
        date_str = datetime.now().strftime("%Y-%m-%d")
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
