import os
import json
import requests
from datetime import datetime, timedelta

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def parse_runs_and_aggregate():
    """读取 all.json 并计算本周、本月、今年的统计数据"""
    try:
	    runs_file = os.path.join(parent, "src", "static", "all.json")
        with open(runs_file, "r", encoding="utf-8") as f:
            runs = json.load(f)
            if not runs:
                return None, None
            
            # 假设数据按时间倒序排列，第一个为最近一次跑步
            latest_run = runs[-1]
            latest_run_details_file =  os.path.join(parent, "public", "data", "coros_details", f"{latest_run.run_id}.json")
            now = datetime.now()
            # 计算时间边界
            # 假设周一为一周的开始
            start_of_week = now - timedelta(days=now.weekday())
            start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

            stats = {
                "weekly": {"distance": 0, "count": 0},
                "monthly": {"distance": 0, "count": 0},
                "yearly": {"distance": 0, "count": 0}
            }

            for run in runs:

                run_date_str = run.get("start_date_local", "")[:10] 
                if not run_date_str:
                    continue
                
                run_date = datetime.strptime(run_date_str, "%Y-%m-%d")
                distance = float(run.get("distance", 0))/1000

                if run_date >= start_of_year:
                    stats["yearly"]["distance"] += distance
                    stats["yearly"]["count"] += 1
                
                if run_date >= start_of_month:
                    stats["monthly"]["distance"] += distance
                    stats["monthly"]["count"] += 1
                
                if run_date >= start_of_week:
                    stats["weekly"]["distance"] += distance
                    stats["weekly"]["count"] += 1

            # 保留两位小数
            stats["yearly"]["distance"] = round(stats["yearly"]["distance"], 2)
            stats["monthly"]["distance"] = round(stats["monthly"]["distance"], 2)
            stats["weekly"]["distance"] = round(stats["weekly"]["distance"], 2)

            return latest_run, stats

    except Exception as e:
        print(f"读取或处理数据失败: {e}")
        return None, None

def check_if_analyzed(run_id):
    runfile = os.path.join(parent, "public", "data", "coros_details", f"{run_id}.json")
	with open(runfile, "r", encoding="utf-8") as f:
	    data = json.load(f)
	if "ai_summary" not in data:
	    return False
	elif data["ai_summary"] == "":
	    return False
	else:
	    return True
		
def analyze_with_gemini(latest_run, stats):
    """调用 Gemini 分析全面数据"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    你现在是一位严谨且专业的马拉松长跑教练。我将提供我最近一次的跑步数据以及本周、本月、今年的累计跑步统计。
    请帮我进行深度复盘，尤其关注长距离耐力积累、配速分布、步频表现和心率控制。
    
    【最新一次跑步数据】
    {json.dumps(latest_run, ensure_ascii=False, indent=2)}
    
    【周期性统计数据】
    - 本周累计：{stats['weekly']['distance']} 公里 ({stats['weekly']['count']} 次)
    - 本月累计：{stats['monthly']['distance']} 公里 ({stats['monthly']['count']} 次)
    - 今年累计：{stats['yearly']['distance']} 公里 ({stats['yearly']['count']} 次)
    
    请按以下结构输出总结（请直接使用 Markdown 格式，不要加多余的客套话）：
    
    ### 1. 最近一次表现分析
    评估本次跑步的质量，点评步频与心率的匹配度，是否有亮点或不足。
    
    ### 2. 周期跑量复盘 (周/月/年)
    结合我本周、本月和今年的累计跑量，评估我的训练连贯性和跑量积累情况。指出当前的月跑量/年跑量是否处于合理的马拉松训练节奏中。
    
    ### 3. 教练建议与加强方向
    给出具体的改进建议。例如：是否需要增加基础有氧（LSD）、是否需要针对心率漂移进行专项训练，或者是否要注意避免过度训练。
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
    response.raise_for_status()
    
    result = response.json()
    return result['candidates'][0]['content']['parts'][0]['text']

def save_to_json(run_id, summary_text):
    runfile = os.path.join(parent, "public", "data", "coros_details", f"{run_id}.json")
    with open(runfile, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["ai_summary"] = summary_text

    with open(runfile, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main():
    latest_run, stats = parse_runs_and_aggregate()
    if not latest_run:
        print("未获取到跑步数据，退出。")
        return

    run_id = latest_run.get("run_id")
    
    print(f"正在检查 {run_id} 的分析状态...")
    if check_if_analyzed(run_id):
        print(f"跑步记录 {run_id} 已经被 Gemini 分析过了，跳过本次执行。")
        return
        
    print(f"记录 {run_id} 尚未分析，正在请求 Gemini...")
    summary = analyze_with_gemini(latest_run, stats)
    
    print("Gemini 分析完成，正在写入 json...")
    save_to_json(run_id, summary)
    print("全部流程执行完毕！")

if __name__ == "__main__":
    parent = os.path.dirname(current) 
    main()
