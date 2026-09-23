#!/usr/bin/env python3
"""Generate the weekly running review report.

The script intentionally uses a public/secret-configured COROS data URL rather than
embedding credentials. It produces a deterministic Markdown report and a small JSON
adjustment request for later automation.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "public/data/summary/reports"
ADJUSTMENT_FILE = ROOT / "config/weekly_adjustment.json"
DATA_URL = os.environ.get("COROS_DATA_URL", "https://run.linwn.net/data/all.json")


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "coros-run-weekly-review/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def get_rows(data):
    if isinstance(data, list):
        return data
    for key in ("activities", "runs", "data", "records"):
        if isinstance(data.get(key), list):
            return data[key]
    raise ValueError("Unsupported COROS JSON structure")


def distance_km(row):
    for k in ("distanceKm", "distance_km"):
        if k in row:
            return float(row[k])
    if "distance" in row:
        value = float(row["distance"])
        return value / 1000 if value > 100 else value
    return 0.0


def hr(row):
    for k in ("average_heartrate", "averageHeartRate", "avg_hr", "heartRate"):
        if row.get(k) is not None:
            return float(row[k])
    return None


def pace_min(row):
    for k in ("pace", "average_pace", "averagePace"):
        if row.get(k) is not None:
            v = float(row[k])
            return v / 60 if v > 20 else v
    if row.get("average_speed"):
        speed = float(row["average_speed"])
        if speed > 0:
            # speed is commonly m/s
            return 16.6666667 / speed
    return None


def row_date(row):
    for k in ("start_date_local", "startDateLocal", "date", "start_time"):
        if row.get(k):
            return parse_date(str(row[k]))
    return None


def main():
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    # Previous completed Monday-Sunday week.
    this_monday = today - timedelta(days=today.weekday())
    week_end = this_monday - timedelta(days=1)
    week_start = week_end - timedelta(days=6)

    data = fetch_json(DATA_URL)
    rows = [r for r in get_rows(data) if isinstance(r, dict)]
    week = [r for r in rows if row_date(r) and week_start <= row_date(r) <= week_end]
    week.sort(key=lambda r: row_date(r))

    total_km = sum(distance_km(r) for r in week)
    hrs = [hr(r) for r in week if hr(r) is not None]
    paces = [pace_min(r) for r in week if pace_min(r) is not None]

    lines = [
        f"# 跑步训练周报｜{week_end.isoformat()}",
        "",
        f"> 统计周期：{week_start.isoformat()} ～ {week_end.isoformat()}（北京时间）",
        "> 主赛：2026-12-20 汕头马拉松｜目标 3:30",
        "> 训练计划：12 周、每周约 4 跑；肇庆半马作为体验赛。",
        "",
        "## 本周概况",
        "",
        f"- 实际跑量：**{total_km:.1f} km**",
        f"- 完成训练：**{len(week)} 次**",
    ]
    if hrs:
        lines.append(f"- 有心率记录的平均 HR：**{statistics.mean(hrs):.0f} bpm**")
    if paces:
        lines.append(f"- 有配速记录的平均配速：**{statistics.mean(paces):.2f} min/km**")

    lines += ["", "## 训练明细", "", "| 日期 | 距离 | 配速 | 平均HR |", "|---|---:|---:|---:|"]
    for r in week:
        d = row_date(r)
        p = pace_min(r)
        h = hr(r)
        lines.append(f"| {d} | {distance_km(r):.1f} km | {p:.2f} min/km | {h:.0f} bpm |" if p is not None and h is not None else f"| {d} | {distance_km(r):.1f} km | — | — |")

    lines += [
        "", "## 计划执行分析", "",
        "当前版本先以 COROS 实际活动数据生成事实层周报；计划课程、恢复与训练负荷的结构化字段接入后，再自动进行逐课计划/实际对比。",
        "",
        "## 下周调整", "",
        "本报告不会仅因单次训练异常自动改变训练计划。只有在连续趋势、关键课表现和恢复指标共同支持时，才提交调整建议。",
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{week_end.isoformat()}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ADJUSTMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADJUSTMENT_FILE.write_text(json.dumps({
        "week_end": week_end.isoformat(),
        "status": "reviewed",
        "plan_adjustment_required": False,
        "reason": "Initial GitHub Actions implementation; no automatic COROS mutation until structured plan/recovery integration is enabled."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
