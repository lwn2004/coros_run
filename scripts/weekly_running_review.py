#!/usr/bin/env python3
"""Hourly Sunday trigger + OpenAI weekly running review.

Flow:
1. Check whether this Sunday's report already exists. If yes, do nothing.
2. Read the published COROS activity feed.
3. If today's Sunday contains a Run with moving time >= 30 minutes, trigger analysis.
4. Otherwise wait until 22:00 Beijing; after that, force analysis.
5. Build a data-rich prompt and ask OpenAI to produce the complete Chinese Markdown report.
6. Write the report and an audit/state JSON file. GitHub Actions commits both files.

The script deliberately does not invent private COROS plan/recovery/HRV data. If a
training plan is available through TRAINING_PLAN_FILE or TRAINING_PLAN_URL it is
included in the analysis. Otherwise the report explicitly records that the plan
was not available to GitHub Actions.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "public/data/summary/reports"
STATE_FILE = ROOT / "config/weekly_adjustment.json"

BEIJING = timezone(timedelta(hours=8))
DATA_URL = os.environ.get("COROS_DATA_URL") or "https://run.linwn.net/data/all.json"
PLAN_URL = os.environ.get("TRAINING_PLAN_URL", "").strip()
PLAN_FILE = os.environ.get("TRAINING_PLAN_FILE", "").strip()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "").strip() or "gpt-5.5"

MIN_TRIGGER_SECONDS = 30 * 60
FORCE_HOUR = 22


def now_bj() -> datetime:
    return datetime.now(timezone.utc).astimezone(BEIJING)


def fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "coros-run-weekly-review/2.0"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "coros-run-weekly-review/2.0"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8")


def get_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ("activities", "runs", "data", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]

    raise ValueError("Unsupported COROS JSON structure")


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    # COROS local timestamps are normally already UTC+8. If no offset is
    # present, interpret them as Beijing time rather than GitHub runner UTC.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=BEIJING)

    return dt.astimezone(BEIJING)


def row_date(row: dict[str, Any]) -> date | None:
    for key in ("start_date_local", "startDateLocal", "date", "start_time"):
        if row.get(key) is not None:
            dt = parse_datetime(row[key])
            if dt:
                return dt.date()
    return None


def distance_km(row: dict[str, Any]) -> float:
    for key in ("distanceKm", "distance_km"):
        if row.get(key) is not None:
            return float(row[key])

    if row.get("distance") is not None:
        value = float(row["distance"])
        return value / 1000.0 if value > 100 else value

    return 0.0


def numeric(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if row.get(key) is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                pass
    return None


def heart_rate(row: dict[str, Any]) -> float | None:
    return numeric(row, (
        "average_heartrate",
        "averageHeartRate",
        "avg_hr",
        "heartRate",
    ))


def cadence(row: dict[str, Any]) -> float | None:
    return numeric(row, (
        "average_cadence",
        "averageCadence",
        "avg_cadence",
        "cadence",
    ))


def pace_min(row: dict[str, Any]) -> float | None:
    for key in ("pace", "average_pace", "averagePace"):
        value = numeric(row, (key,))
        if value is not None:
            return value / 60.0 if value > 20 else value

    speed = numeric(row, ("average_speed", "averageSpeed"))
    if speed and speed > 0:
        # Existing COROS feed uses km/h-like speed in this repository.
        return 60.0 / speed

    return None


def moving_seconds(row: dict[str, Any]) -> int:
    value = row.get("moving_time", row.get("movingTime", row.get("duration")))

    if value is None:
        return 0

    if isinstance(value, (int, float)):
        # This repository's COROS data commonly stores duration in seconds.
        return max(0, int(float(value)))

    text = str(value).strip()
    if not text:
        return 0

    if text.isdigit():
        return int(text)

    # HH:MM:SS or MM:SS
    match = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", text)
    if match:
        a, b, c = match.groups()
        if c is None:
            return int(a) * 60 + int(b)
        return int(a) * 3600 + int(b) * 60 + int(c)

    return 0


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_pace(minutes: float | None) -> str:
    if minutes is None or minutes <= 0:
        return "—"
    total = int(round(minutes * 60))
    return f"{total // 60}:{total % 60:02d}/km"


def activity_type(row: dict[str, Any]) -> str:
    return str(row.get("type", row.get("sport", row.get("activity_type", "")))).strip()


def is_run(row: dict[str, Any]) -> bool:
    value = activity_type(row).lower()
    return any(token in value for token in ("run", "running", "跑"))


def sort_key(row: dict[str, Any]) -> datetime:
    for key in ("start_date_local", "startDateLocal", "date", "start_time"):
        dt = parse_datetime(row.get(key))
        if dt:
            return dt
    return datetime.min.replace(tzinfo=BEIJING)


def period_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    run_rows = [r for r in rows if is_run(r)]
    distances = [distance_km(r) for r in run_rows]
    hrs = [heart_rate(r) for r in run_rows if heart_rate(r) is not None]
    paces = [pace_min(r) for r in run_rows if pace_min(r) is not None]
    durations = [moving_seconds(r) for r in run_rows]

    return {
        "runs": len(run_rows),
        "distance_km": round(sum(distances), 2),
        "moving_minutes": round(sum(durations) / 60, 1),
        "avg_hr": round(statistics.mean(hrs), 1) if hrs else None,
        "avg_pace_min_km": round(statistics.mean(paces), 3) if paces else None,
    }


def load_plan() -> tuple[str, str]:
    if PLAN_URL:
        try:
            return "url", fetch_text(PLAN_URL)
        except Exception as exc:
            return "unavailable", f"TRAINING_PLAN_URL failed: {exc}"

    path = Path(PLAN_FILE) if PLAN_FILE else ROOT / "config/training_plan.md"
    if not path.is_absolute():
        path = ROOT / path

    if path.exists():
        return "file", path.read_text(encoding="utf-8")

    return "unavailable", "No training plan file was found."


def compact_activity(row: dict[str, Any]) -> dict[str, Any]:
    dt = parse_datetime(
        row.get("start_date_local", row.get("startDateLocal", row.get("date")))
    )

    return {
        "run_id": row.get("run_id", row.get("runId", row.get("id"))),
        "date": dt.date().isoformat() if dt else None,
        "weekday": dt.strftime("%A") if dt else None,
        "type": activity_type(row),
        "distance_km": round(distance_km(row), 3),
        "moving_time": fmt_duration(moving_seconds(row)),
        "moving_seconds": moving_seconds(row),
        "pace": fmt_pace(pace_min(row)),
        "average_hr": heart_rate(row),
        "average_cadence": cadence(row),
        "city": row.get("city"),
    }


def build_data(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    monday = today - timedelta(days=today.weekday())
    week_start = monday
    week_end = today

    four_week_start = monday - timedelta(days=21)
    one_month_start = today - timedelta(days=29)
    one_year_start = today - timedelta(days=364)

    def between(start: date, end: date) -> list[dict[str, Any]]:
        return [
            r for r in rows
            if row_date(r) is not None and start <= row_date(r) <= end
        ]

    week = sorted(between(week_start, week_end), key=sort_key)
    four_week = sorted(between(four_week_start, week_end), key=sort_key)
    month = between(one_month_start, today)
    year = between(one_year_start, today)
    sunday = [
        r for r in week
        if row_date(r) == today and is_run(r)
    ]

    return {
        "week": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
            "activities": [compact_activity(r) for r in week],
            "stats": period_stats(week),
        },
        "last_4_weeks": {
            "start": four_week_start.isoformat(),
            "end": week_end.isoformat(),
            "stats": period_stats(four_week),
        },
        "last_30_days": period_stats(month),
        "last_365_days": period_stats(year),
        "sunday_runs": [compact_activity(r) for r in sorted(sunday, key=sort_key)],
    }


def trigger_for(today_dt: datetime, data: dict[str, Any]) -> tuple[bool, str, dict[str, Any] | None]:
    sunday_runs = data["sunday_runs"]
    qualifying = [
        r for r in sunday_runs
        if r["moving_seconds"] >= MIN_TRIGGER_SECONDS
    ]

    if qualifying:
        # If multiple qualifying runs exist, use the latest one as the trigger.
        return True, "run_detected", qualifying[-1]

    if today_dt.hour >= FORCE_HOUR:
        return True, "timeout", None

    return False, "waiting", None


def openai_response(prompt: str) -> str:
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": (
                    "你是一名专业耐力跑训练分析助手。"
                    "请严格基于提供的数据进行分析，不要虚构COROS、HRV、训练负荷或训练计划数据。"
                    "当前目标赛事为2026-12-20汕头马拉松，目标成绩3:30。"
                    "用户要求的是客观训练复盘，而不是鼓励性文字。"
                    "不要因为一次偶发训练偏差就修改计划；只有趋势、恢复状态和关键课表现形成充分证据时才提出调整。"
                    "如果训练计划、恢复或HRV数据没有提供，要明确说明数据缺失。"
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "coros-run-weekly-review/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc

    # Responses API returns output message content containing output_text.
    for item in result.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"].strip()

    if result.get("output_text"):
        return str(result["output_text"]).strip()

    raise RuntimeError("OpenAI response did not contain output text.")


def build_prompt(
    report_date: date,
    trigger: str,
    trigger_activity: dict[str, Any] | None,
    data: dict[str, Any],
    plan_source: str,
    plan_text: str,
) -> str:
    plan_note = (
        plan_text
        if plan_source in ("file", "url")
        else f"[训练计划不可用] {plan_text}"
    )

    trigger_text = (
        json.dumps(trigger_activity, ensure_ascii=False, indent=2)
        if trigger_activity
        else "周日截至22:00没有发现移动时间≥30分钟的跑步，本次按22:00超时规则强制分析。"
    )

    return f"""
请生成一份完整的中文 Markdown 跑步周报，可直接保存为：
public/data/summary/reports/{report_date.isoformat()}.md

统计周期：{data["week"]["start"]} ～ {data["week"]["end"]}（北京时间）
主赛：2026-12-20 汕头马拉松
目标：3:30
本次触发方式：{trigger}
本次触发活动：
{trigger_text}

必须包含：
1. 本周训练概况：跑量、次数、总移动时间。
2. 计划与实际执行情况。如果训练计划数据可用，逐项比较日期、课程类型、计划距离/配速与实际执行；如果不可用，明确写出“训练计划数据未提供给GitHub Actions”，不要猜测。
3. Easy / Recovery、阈值、马拉松配速、长距离等训练类型的执行情况；只能根据实际数据识别，不能凭空给课程贴标签。
4. 本周关键课表现：距离、配速、平均HR、平均步频（如果有）。
5. 最近4周趋势，并比较本周与4周趋势。
6. 最近30天和365天统计。
7. 恢复、HRV、训练负荷：只有输入数据存在时才分析；没有数据就明确说明缺失。
8. 执行偏差、疲劳或恢复风险。
9. 对2026-12-20汕头马拉松3:30目标的训练意义。不要预测比赛结果。
10. 下周训练建议。
11. 如果确实需要修改未来训练计划，必须列出：
   - 日期
   - 原计划
   - 新计划
   - 修改原因
   如果不需要修改，明确写“无需调整”。
12. 最后增加“自动化信息”，注明本周报告由GitHub Actions触发，触发原因是“发现周日≥30分钟跑步”或“22:00超时”。

训练计划：
---
{plan_note}
---

本周及趋势数据：
---
{json.dumps(data, ensure_ascii=False, indent=2)}
---

要求：
- 只输出最终Markdown正文，不要代码围栏。
- 不要虚构任何数据。
- 配速统一使用 min/km。
- 日期使用 YYYY-MM-DD。
- 结论要与数据对应，避免空泛的表扬。
""".strip()


def main() -> int:
    now = now_bj()
    today = now.date()

    # Scheduled execution is Sunday only. Manual dispatch is also allowed, but
    # it uses the current Beijing date and therefore should normally be run Sunday.
    if today.weekday() != 6:
        print(f"Today is {today.isoformat()} ({now.isoformat()}); not Sunday. Nothing to do.")
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{today.isoformat()}.md"

    # Primary idempotency guard.
    if report_path.exists() and report_path.stat().st_size > 0:
        print(f"Report already exists: {report_path}")
        return 0

    print(f"Checking COROS data at {DATA_URL}")
    raw = fetch_json(DATA_URL)
    rows = get_rows(raw)
    data = build_data(rows, today)

    should_run, trigger, trigger_activity = trigger_for(now, data)

    print(
        f"Beijing time={now.isoformat()}, trigger={trigger}, "
        f"Sunday runs={len(data['sunday_runs'])}"
    )

    if not should_run:
        print("No qualifying Sunday run and it is before 22:00. Waiting for next hourly run.")
        return 0

    plan_source, plan_text = load_plan()
    prompt = build_prompt(
        report_date=today,
        trigger=trigger,
        trigger_activity=trigger_activity,
        data=data,
        plan_source=plan_source,
        plan_text=plan_text,
    )

    print(f"Generating report with OpenAI model={OPENAI_MODEL}")
    report = openai_response(prompt)

    if not report.startswith("#"):
        report = f"# 跑步训练周报｜{today.isoformat()}\n\n{report}"

    report_path.write_text(report.rstrip() + "\n", encoding="utf-8")

    state = {
        "week_end": today.isoformat(),
        "status": "completed",
        "trigger": trigger,
        "trigger_activity_id": (
            trigger_activity.get("run_id") if trigger_activity else None
        ),
        "generated_at": now.isoformat(),
        "report": str(report_path.relative_to(ROOT)),
        "plan_source": plan_source,
        "openai_model": OPENAI_MODEL,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Final local verification before GitHub Actions commits.
    if not report_path.exists() or report_path.stat().st_size == 0:
        raise RuntimeError(f"Report verification failed: {report_path}")

    print(f"Generated and verified: {report_path}")
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
