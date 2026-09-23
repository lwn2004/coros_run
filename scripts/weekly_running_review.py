#!/usr/bin/env python3
"""Generate the weekly running review report.

Phase 1 uses the user's published COROS data feed and writes a factual report.
A repository GitHub Action cannot directly use the private COROS connector, so
COROS plan mutations are deliberately not attempted here. The ChatGPT-side
automation remains responsible for private COROS review/changes until a supported
external COROS API/write credential is available.
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
        if row.get(k) is not None:
            return float(row[k])
    if row.get("distance") is not None:
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
            value = float(row[k])
            return value / 60 if value > 20 else value
    if row.get("average_speed"):
        speed = float(row["average_speed"])
        if speed > 0:
            return 16.6666667 / speed
    return None


def row_date(row):
    for k in ("start_date_local", "startDateLocal", "date", "start_time"):
        if row.get(k):
            return parse_date(str(row[k]))
    return None


def fmt_pace(minutes):
    if minutes is None:
        return "—"
    total = round(minutes * 60)
    return f"{total // 60}:{total % 60:02d}"


def main():
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    monday = today - timedelta(days=today.weekday())
    week_end = monday - timedelta(days=1)
    week_start = week_end - timedelta(days=6)

    data = fetch_json(DATA_URL)
    rows = [r for r in get_rows(data) if isinstance(r, dict)]
    week = [r for r in rows if row_date(r) and week_start <= row_date(r) <= week_end]
    week.sort(key=lambda r: row_date(r))

    total_km = sum(distance_km(r) for r in week)
    hrs = [hr(r) for r in week if hr(r) is not None]
    paces = [pace_min(r) for r in week if pace_min(r) is not None]

    lines = [
        f"# 跑步训练周报｜{week_end.isoformat()}", "",
        f"> 统计周期：{week_start.isoformat()} ～ {week_end.isoformat()}（北京时间）",
        "> 主赛：2026-12-20 汕头马拉松｜目标 3:30",
        "> 肇庆半马：2026-11-29｜体验赛定位", "",
        "## 本周概况", "",
        f"- 实际跑量：**{total_km:.1f} km**",
        f"- 记录训练：**{len(week)} 次**",
    ]
    if hrs:
        lines.append(f"- 有心率记录的平均 HR：**{statistics.mean(hrs):.0f} bpm**")
    if paces:
        lines.append(f"- 有配速记录的平均配速：**{fmt_pace(statistics.mean(paces))}/km**")

    lines += ["", "## 训练明细", "", "| 日期 | 距离 | 配速 | 平均HR |", "|---|---:|---:|---:|"]
    for r in week:
        lines.append(f"| {row_date(r)} | {distance_km(r):.1f} km | {fmt_pace(pace_min(r))} | "
                     + (f"{hr(r):.0f} bpm |" if hr(r) is not None else "— |"))

    lines += [
        "", "## 计划执行分析", "",
        "当前为 GitHub Actions 第一阶段：先生成可靠的实际训练事实层。",
        "私有 COROS 计划、恢复与训练负荷字段尚未暴露给 GitHub Actions，因此本阶段不会伪造逐课对比或直接修改 COROS。",
        "", "## 下周调整", "",
        "本阶段默认不自动修改 COROS。后续接入可写 COROS API 后，只有趋势证据充分时才调整，并记录原计划、新计划和原因。",
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{week_end.isoformat()}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ADJUSTMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADJUSTMENT_FILE.write_text(json.dumps({
        "week_end": week_end.isoformat(),
        "status": "facts_only",
        "plan_adjustment_required": False,
        "reason": "GitHub Actions currently has no supported private COROS write API."
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
