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


# 高于本次现场一氧化碳表的最大值（约 14），低于演示注入的 86。只作筛查关注值，不是规范限值。
CO_ATTENTION_PPM = 30.0
_FIELD_RULES = {
    "CO": {"high": CO_ATTENTION_PPM, "unit": "ppm", "kind": "co_high", "label": "一氧化碳浓度偏高"},
}


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = round(fraction * (len(sorted_values) - 1))
    return sorted_values[index]


def _series_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
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


def field_exceedances(records: list[dict[str, Any]] | tuple, metric: str) -> list[dict[str, Any]]:
    rule = _FIELD_RULES.get(metric)
    if rule is None:
        return []
    findings = []
    for record in records:
        value = float(record["value"])
        if value <= rule["high"]:
            continue
        findings.append(
            {
                "id": f"field-{metric}-{record['station']}-{record['timestamp']}",
                "kind": rule["kind"],
                "label": rule["label"],
                "station": record["station"],
                "timestamp": record["timestamp"],
                "value": value,
                "unit": rule["unit"],
                "baseline": f"筛查关注值 {rule['high']:g} {rule['unit']}，高于本次现场表已见范围，不是规范限值",
                "detail": "现场序列超出筛查关注值，需人工核对。本条不是模拟注入。",
                "simulated": False,
            }
        )
    return findings


def detect_sensor_anomalies() -> dict[str, Any]:
    findings = _simulated_findings()
    series = {metric: list(get_environment_records(metric)) for metric in ("CO", "VI", "LA", "WS")}
    summaries = {metric: _series_summary(records) for metric, records in series.items()}
    field_findings = field_exceedances(series["CO"], "CO")[:8]
    if field_findings:
        conclusion = (
            f"现场一氧化碳有 {len(field_findings)} 条读数超过筛查关注值 {CO_ATTENTION_PPM:g} ppm，已单独列出。"
            "能见度、风速和光照仍只做测点范围核对。模拟事件不计入这次现场核对。"
        )
    else:
        conclusion = (
            "现场一氧化碳、能见度、风速和光照都落在各测点已有记录范围内，"
            f"一氧化碳未超过筛查关注值 {CO_ATTENTION_PPM:g} ppm，本次不作为异常。"
        )
    return {
        "tunnel": "色尔岗曲隧道",
        "historical": True,
        "demo": bool(findings),
        "notes": [
            "现场四类环境序列已按测点核对，未超过关注值的不作为异常。",
            "模拟事件单独列出，提交后才会发给 MoMA。",
            "现场环境表没有温度序列，温度条目完全是演示假设。",
        ],
        "field_check": {
            "conclusion": conclusion,
            "co": summaries["CO"],
            "vi": summaries["VI"],
            "light": summaries["LA"],
            "ws": summaries["WS"],
            "temperature": "现场环境表没有温度序列，不判定温度。",
            "attention_ppm": CO_ATTENTION_PPM,
        },
        "offline_review": OFFLINE_REVIEW,
        "scanned": {
            "co_records": summaries["CO"]["records"],
            "vi_records": summaries["VI"]["records"],
            "light_records": summaries["LA"]["records"],
            "ws_records": summaries["WS"]["records"],
        },
        "field_findings": field_findings,
        "findings": findings,
    }
