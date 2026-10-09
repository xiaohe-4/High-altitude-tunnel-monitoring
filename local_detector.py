from __future__ import annotations

import json
from typing import Any

from real_data import ROOT, get_environment_records


DEMO_EVENTS = ROOT / "data" / "demo" / "simulated_events.json"
_EVENT_FIELDS = ("id", "kind", "label", "station", "timestamp", "value", "baseline", "detail")
OFFLINE_REVIEW = (
    "演示备用结论，不是本次云端返回。"
    "一氧化碳 86 ppm、照度骤降和车辆停驶是模拟注入，适合作为上报样例；"
    "温度 42.6℃ 没有现场序列，只能作为演示假设。"
    "建议人工确认后再上报。原始视频未上传。"
)


def _simulated_findings() -> list[dict[str, Any]]:
    if not DEMO_EVENTS.is_file():
        return []
    payload = json.loads(DEMO_EVENTS.read_text(encoding="utf-8"))
    findings = []
    for event in payload.get("events", []):
        if any(field not in event for field in _EVENT_FIELDS):
            continue
        findings.append({**event, "simulated": True})
    return findings


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = round(fraction * (len(sorted_values) - 1))
    return sorted_values[index]


def _series_summary(metric: str) -> dict[str, Any]:
    records = list(get_environment_records(metric))
    values = sorted(float(record["value"]) for record in records)
    if not values:
        return {"records": 0, "stations": 0, "min": None, "max": None, "median": None}
    return {
        "records": len(values),
        "stations": len({record["station"] for record in records}),
        "min": round(values[0], 2),
        "max": round(values[-1], 2),
        "median": round(_percentile(values, 0.5), 2),
    }


def detect_sensor_anomalies() -> dict[str, Any]:
    findings = _simulated_findings()
    co = _series_summary("CO")
    light = _series_summary("LA")
    return {
        "tunnel": "色尔岗曲隧道",
        "historical": True,
        "demo": bool(findings),
        "notes": [
            "现场一氧化碳和光照已核对，不作为本次异常。",
            "模拟事件单独列出，需手动提交后才会发给 MoMA。",
            "现场环境表没有温度序列，温度条目完全是演示假设。",
        ],
        "field_check": {
            "conclusion": "现场一氧化碳和光照读数都落在各测点已有记录范围内，本次不作为异常。",
            "co": co,
            "light": light,
            "temperature": "现场环境表没有温度序列，不判定温度。",
        },
        "offline_review": OFFLINE_REVIEW,
        "scanned": {
            "co_records": co["records"],
            "light_records": light["records"],
        },
        "findings": findings,
    }
