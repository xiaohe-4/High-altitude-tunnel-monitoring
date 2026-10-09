from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from local_detector import OFFLINE_REVIEW, detect_sensor_anomalies
from moma_client import MomaChatClient
from real_data import METRICS, ROOT, TRUE_DATA_DIR, get_environment_records, get_site_faults, list_data_files
from vision_detector import load_video_detections, scan_local_video, vision_status

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "tunnel.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Tunnel Monitoring API", version="1.0.0")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tunnel_id TEXT,
                point_id TEXT,
                timestamp TEXT,
                temperature_c REAL,
                humidity_pct REAL,
                co_ppm REAL,
                ventilation_status TEXT,
                power_status TEXT,
                data_quality TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS device_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tunnel_id TEXT,
                device_id TEXT,
                device_type TEXT,
                timestamp TEXT,
                status TEXT,
                fault_code TEXT,
                fault_desc TEXT,
                recovery_flag INTEGER,
                network_status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tunnel_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                tunnel_id TEXT,
                point_id TEXT,
                event_type TEXT,
                risk_level TEXT,
                confidence REAL,
                status TEXT,
                start_time TEXT,
                end_time TEXT,
                evidence_chain TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS risk_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                risk_level TEXT,
                confidence REAL,
                primary_factors TEXT,
                actions TEXT,
                next_check TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()


class SensorPayload(BaseModel):
    tunnel_id: str
    point_id: str
    timestamp: str
    temperature_c: float | None = None
    humidity_pct: float | None = None
    co_ppm: float | None = None
    ventilation_status: str | None = None
    power_status: str | None = None
    data_quality: str | None = None


class DeviceLogPayload(BaseModel):
    tunnel_id: str
    device_id: str
    device_type: str | None = None
    timestamp: str
    status: str | None = None
    fault_code: str | None = None
    fault_desc: str | None = None
    recovery_flag: bool | None = False
    network_status: str | None = None


class EventPayload(BaseModel):
    event_id: str
    tunnel_id: str
    point_id: str
    event_type: str
    risk_level: str
    confidence: float | None = None
    status: str | None = None
    start_time: str
    end_time: str | None = None
    evidence_chain: list[dict[str, Any]] | None = None


class RiskPayload(BaseModel):
    event_id: str
    risk_level: str
    confidence: float | None = None
    primary_factors: list[dict[str, Any]] | None = None
    actions: list[str] | None = None
    next_check: str | None = None


MOMA_STRATEGIES: dict[str, dict[str, Any]] = {
    "cost": {
        "label": "成本优先",
        "temperature": 0.1,
        "top_p": 0.8,
        "max_tokens": 256,
        "style": "回答尽量短，只保留结论、一条证据和一条人工建议。",
    },
    "balanced": {
        "label": "均衡优先",
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 384,
        "style": "兼顾完整和篇幅，输出结论、证据、人工建议。",
    },
    "quality": {
        "label": "效果优先",
        "temperature": 0.3,
        "top_p": 0.95,
        "max_tokens": 512,
        "style": "优先把能核对的证据写清楚，仍须区分历史记录和实时状态，不要编造阈值。",
    },
}

MOMA_TASKS: dict[str, dict[str, Any]] = {
    "patrol": {
        "label": "常规巡检",
        "sensor_limit": 4,
        "fault_limit": 2,
        "instruction": "任务是常规巡检摘要。只概括历史曲线形态和需要留档的事项，不要展开推测。",
    },
    "review": {
        "label": "异常复核",
        "sensor_limit": 12,
        "fault_limit": 5,
        "instruction": "任务是异常复核。指出读数起伏和未恢复故障是否需要人工核对；信息不足时明确写无法判定风险等级。",
    },
    "fusion": {
        "label": "多源关联",
        "sensor_limit": 8,
        "fault_limit": 3,
        "instruction": "任务是把所选测点的历史读数与设备故障摘要放在一起看。只说明两类记录里能直接读到的关系，不要把同时出现说成因果关系。",
    },
}

_MOMA_SESSIONS: dict[str, dict[str, Any]] = {}
_MOMA_SESSION_LIMIT = 32


class MomaAnalysisRequest(BaseModel):
    metric: str = "CO"
    station: str | None = None
    question: str | None = Field(default=None, max_length=500)
    strategy: Literal["cost", "balanced", "quality"] = "balanced"
    task: Literal["patrol", "review", "fusion"] = "fusion"
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F-]{36}$")


def reset_moma_sessions() -> None:
    _MOMA_SESSIONS.clear()


def compact_moma_usage(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    compact = {
        key: usage[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(usage.get(key), int)
    }
    return compact or None


def visible_moma_reply(content: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    if re.search(r"<think>", text, flags=re.IGNORECASE):
        text = re.split(r"<think>", text, maxsplit=1, flags=re.IGNORECASE)[0]
    return text.strip()


def _trim_moma_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(messages) <= 8:
        return messages
    return [messages[0], messages[1], *messages[-6:]]


def _remember_moma_session(
    session_id: str,
    messages: list[dict[str, str]],
    meta: dict[str, Any],
    counts: dict[str, int],
) -> None:
    if session_id not in _MOMA_SESSIONS and len(_MOMA_SESSIONS) >= _MOMA_SESSION_LIMIT:
        _MOMA_SESSIONS.pop(next(iter(_MOMA_SESSIONS)))
    _MOMA_SESSIONS[session_id] = {"messages": messages, "meta": meta, "counts": counts}


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    _load_route_cache()
    asyncio.create_task(_warm_demo_route())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "database": str(DB_PATH)}


@app.get("/api/v1/real-data/overview")
async def real_data_overview() -> dict[str, Any]:
    metrics = {}
    for code, config in METRICS.items():
        records = get_environment_records(code)
        latest_timestamp = records[-1]["timestamp"] if records else None
        latest_records = [record for record in records if record["timestamp"] == latest_timestamp]
        metrics[code] = {
            "label": config["label"],
            "source_file": config["file"],
            "record_count": len(records),
            "stations": sorted({record["station"] for record in records}),
            "latest_timestamp": latest_timestamp,
            "latest_value": round(sum(record["value"] for record in latest_records) / len(latest_records), 3)
            if latest_records
            else None,
            "latest_station_count": len({record["station"] for record in latest_records}),
        }

    faults = get_site_faults()
    recovered_count = sum(event["recovered"] for event in faults)
    return {
        "tunnel_name": "色尔岗曲隧道",
        "metrics": metrics,
        "fault_summary": {
            "total": len(faults),
            "recovered": recovered_count,
            "unresolved": len(faults) - recovered_count,
        },
        "files": list_data_files(),
    }


@app.get("/api/v1/real-data/environment")
async def real_environment(
    metric: str = Query(default="CO"),
    station: str | None = Query(default=None),
    limit: int = Query(default=240, ge=1, le=2000),
) -> dict[str, Any]:
    if metric not in METRICS:
        raise HTTPException(status_code=422, detail="metric must be one of CO, VI, LA, WS")
    records = list(get_environment_records(metric))
    stations = sorted({record["station"] for record in records})
    if station:
        records = [record for record in records if record["station"] == station]
    return {
        "metric": metric,
        "label": METRICS[metric]["label"],
        "source_file": METRICS[metric]["file"],
        "stations": stations,
        "count": len(records),
        "records": records[-limit:],
    }


@app.get("/api/v1/real-data/faults")
async def real_faults(limit: int = Query(default=12, ge=1, le=100)) -> dict[str, Any]:
    faults = get_site_faults()
    recovered_count = sum(event["recovered"] for event in faults)
    return {
        "total": len(faults),
        "recovered": recovered_count,
        "unresolved": len(faults) - recovered_count,
        "events": list(faults[:limit]),
    }


def _safe_file(directory: Path, relative_path: str) -> Path:
    resolved_directory = directory.resolve()
    resolved_file = (resolved_directory / relative_path).resolve()
    try:
        resolved_file.relative_to(resolved_directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    if not resolved_file.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return resolved_file


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "index.html")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(ROOT / "styles.css")


@app.get("/app.js")
async def app_script() -> FileResponse:
    return FileResponse(ROOT / "app.js")


@app.get("/mock_data.json")
async def mock_data() -> FileResponse:
    return FileResponse(ROOT / "mock_data.json")


@app.get("/data/tunnel_day_dataset.json")
async def synthetic_dataset() -> FileResponse:
    return FileResponse(ROOT / "data" / "tunnel_day_dataset.json")


@app.get("/data/videos/{filename:path}")
async def video_file(filename: str) -> FileResponse:
    return FileResponse(_safe_file(ROOT / "data" / "videos", filename))


@app.get("/data/true_data/{filename:path}")
async def true_data_file(filename: str) -> FileResponse:
    return FileResponse(_safe_file(TRUE_DATA_DIR, filename), filename=Path(filename).name)


@app.post("/api/v1/sensor/upload")
async def upload_sensor(payload: SensorPayload) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sensor_data (
                tunnel_id, point_id, timestamp, temperature_c, humidity_pct,
                co_ppm, ventilation_status, power_status, data_quality
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.tunnel_id,
                payload.point_id,
                payload.timestamp,
                payload.temperature_c,
                payload.humidity_pct,
                payload.co_ppm,
                payload.ventilation_status,
                payload.power_status,
                payload.data_quality,
            ),
        )
        conn.commit()
    return {"status": "ok", "message": "sensor data uploaded", "point_id": payload.point_id}


@app.post("/api/v1/device/log")
async def upload_device_log(payload: DeviceLogPayload) -> dict[str, Any]:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO device_logs (
                tunnel_id, device_id, device_type, timestamp, status,
                fault_code, fault_desc, recovery_flag, network_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.tunnel_id,
                payload.device_id,
                payload.device_type,
                payload.timestamp,
                payload.status,
                payload.fault_code,
                payload.fault_desc,
                int(payload.recovery_flag or False),
                payload.network_status,
            ),
        )
        conn.commit()
    return {"status": "ok", "message": "device log uploaded", "device_id": payload.device_id}


@app.post("/api/v1/event/upload")
async def upload_event(payload: EventPayload) -> dict[str, Any]:
    evidence = json.dumps(payload.evidence_chain, ensure_ascii=False) if payload.evidence_chain else None
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO tunnel_events (
                    event_id, tunnel_id, point_id, event_type, risk_level,
                    confidence, status, start_time, end_time, evidence_chain
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.event_id,
                    payload.tunnel_id,
                    payload.point_id,
                    payload.event_type,
                    payload.risk_level,
                    payload.confidence,
                    payload.status,
                    payload.start_time,
                    payload.end_time,
                    evidence,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"event already exists: {payload.event_id}") from exc
    return {"status": "ok", "message": "event uploaded", "event_id": payload.event_id}


@app.post("/api/v1/risk/upload")
async def upload_risk(payload: RiskPayload) -> dict[str, Any]:
    primary = json.dumps(payload.primary_factors, ensure_ascii=False) if payload.primary_factors else None
    actions = json.dumps(payload.actions, ensure_ascii=False) if payload.actions else None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO risk_results (event_id, risk_level, confidence, primary_factors, actions, next_check)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.event_id,
                payload.risk_level,
                payload.confidence,
                primary,
                actions,
                payload.next_check,
            ),
        )
        conn.commit()
    return {"status": "ok", "message": "risk result uploaded", "event_id": payload.event_id}


@app.get("/api/v1/overview")
async def overview() -> dict[str, Any]:
    with get_connection() as conn:
        sensor_count = conn.execute("SELECT COUNT(*) FROM sensor_data").fetchone()[0]
        device_count = conn.execute("SELECT COUNT(*) FROM device_logs").fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM tunnel_events").fetchone()[0]
        latest = conn.execute(
            "SELECT event_id, risk_level, confidence FROM tunnel_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return {
        "sensor_count": sensor_count,
        "device_count": device_count,
        "event_count": event_count,
        "latest_event": dict(latest) if latest else None,
    }


@app.get("/api/v1/events")
async def get_events(
    point_id: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    query = "SELECT * FROM tunnel_events WHERE 1=1"
    params: list[Any] = []
    if point_id:
        query += " AND point_id = ?"
        params.append(point_id)
    if risk_level:
        query += " AND risk_level = ?"
        params.append(risk_level)
    query += " ORDER BY start_time DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        event = dict(row)
        event["evidence_chain"] = json.loads(event["evidence_chain"]) if event["evidence_chain"] else []
        result.append(event)
    return result


def _verification_messages(findings: list[dict[str, Any]], source: str) -> list[dict[str, str]]:
    payload = {
        "tunnel": "色尔岗曲隧道",
        "source": source,
        "notice": "带 simulated 标记的条目是演示注入，不是现场实测。请在结论中写明模拟，并判断是否适合作为上报样例。",
        "findings": findings,
        "question": "请逐条判断这些筛查结果更像真实异常、证据不足，还是不像异常，并给出是否建议人工上报。",
    }
    return [
        {
            "role": "system",
            "content": (
                "你是隧道异常复核助手。只根据给出的条目判断。"
                "带 simulated 标记的是演示注入，结论里要写明模拟，不要说成现场实测。"
                "每条用一句话给出判定：疑似真实、证据不足或不像异常。不要输出思考过程。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


CATEGORY_ROUTES: dict[str, tuple[str, str, str, str]] = {
    "co_high": ("一氧化碳", "balanced", "review", "环境时序复核，走均衡优先"),
    "light_drop": ("照度", "cost", "review", "照度质量检查，走成本优先"),
    "light_high": ("照度", "cost", "review", "照度质量检查，走成本优先"),
    "temperature_high": ("温度", "cost", "review", "没有现场温度序列，短复核，走成本优先"),
    "vehicle_stop": ("车辆停驶", "quality", "review", "紧急告警，走效果优先"),
    "video_object": ("画面目标", "quality", "review", "画面目标复核，走效果优先"),
    "video_dense": ("车流密度", "balanced", "review", "单帧车辆数量，走均衡优先"),
}
_ROUTE_ORDER = ("一氧化碳", "照度", "温度", "车辆停驶", "画面目标", "车流密度", "其他")
_ROUTE_TOKEN_CAP = {"cost": 448, "balanced": 512, "quality": 640}
_ROUTE_CALL_TIMEOUT = 45
_ROUTE_JOBS: dict[str, asyncio.Task] = {}
_ROUTE_ERRORS: dict[str, dict[str, Any]] = {}
_ROUTE_CACHE: dict[str, dict[str, Any]] = {}
_ROUTE_CACHE_LIMIT = 8
_ROUTE_CACHE_PATH = DATA_DIR / "demo" / "moma_route_cache.json"
_route_lock: asyncio.Lock | None = None


def _category_of(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    return CATEGORY_ROUTES.get(
        str(finding.get("kind") or ""),
        ("其他", "balanced", "review", "未单列的类型，走均衡优先"),
    )


def build_routing_plan(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for finding in findings:
        category, strategy_id, task_id, reason = _category_of(finding)
        slot = grouped.get(category)
        if slot is None:
            strategy = MOMA_STRATEGIES[strategy_id]
            task = MOMA_TASKS[task_id]
            slot = {
                "category": category,
                "strategy": strategy_id,
                "strategy_label": strategy["label"],
                "task": task_id,
                "task_label": task["label"],
                "reason": reason,
                "temperature": strategy["temperature"],
                "top_p": strategy["top_p"],
                "max_tokens": _ROUTE_TOKEN_CAP[strategy_id],
                "count": 0,
            }
            grouped[category] = slot
        slot["count"] += 1
    return [grouped[name] for name in _ROUTE_ORDER if name in grouped]


def _compact_finding(finding: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: finding[key]
        for key in ("label", "station", "value", "unit", "baseline", "detail", "simulated")
        if key in finding
    }
    return compact


def _category_route_messages(item: dict[str, Any], findings: list[dict[str, Any]]) -> list[dict[str, str]]:
    lines = []
    for finding in findings:
        reading = f"{finding.get('value', '')}{finding.get('unit', '')}".strip()
        lines.append(f"{finding.get('label', '')} {reading}｜{finding.get('detail', '')}".strip())
    return [
        {
            "role": "system",
            "content": (
                "你是隧道异常复核助手。条目是演示注入，不是现场实测。"
                "只用一行，格式固定：判定：疑似真实或证据不足或不像异常；建议上报：是或否。"
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]


def _suggests_report(reply: str) -> bool:
    return "建议上报：是" in reply.replace(":", "：")


def _merge_route_replies(routes: list[dict[str, Any]]) -> str:
    lines = []
    for route in routes:
        reply = str(route.get("reply") or "").strip()
        if reply:
            lines.append(f"{route['category']}：{reply}")
    if not lines:
        return ""
    report = any(_suggests_report(str(route.get("reply") or "")) for route in routes)
    lines.append("是否合并上报：" + ("是" if report else "否"))
    return "\n".join(lines)


async def _ask_moma(
    messages: list[dict[str, str]],
    strategy_id: str = "balanced",
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    strategy = MOMA_STRATEGIES[strategy_id]
    client = MomaChatClient(timeout=timeout)
    started = time.perf_counter()
    token_limit = max_tokens if max_tokens is not None else min(1024, strategy["max_tokens"])
    response = await run_in_threadpool(
        client.chat_completion,
        messages,
        max_tokens=token_limit,
        temperature=strategy["temperature"],
        top_p=strategy["top_p"],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.get("status") == "error":
        detail = response.get("detail", "")
        if "not configured" in detail:
            status_code = 503
        elif "timed out" in detail.lower() or "timeout" in detail.lower():
            status_code = 504
        else:
            status_code = 502
        raise HTTPException(status_code=status_code, detail=detail)
    try:
        raw_answer = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="MoMA 返回中未找到聊天补全内容") from exc
    answer = visible_moma_reply(raw_answer)
    if not answer:
        raise HTTPException(status_code=502, detail="MoMA 没有形成可展示的复核结论。")
    return {
        "model": response.get("model") or client.model,
        "reply": answer,
        "usage": compact_moma_usage(response.get("usage")),
        "elapsed_ms": elapsed_ms,
    }


@app.get("/api/v1/anomalies")
async def sensor_anomalies() -> dict[str, Any]:
    report = detect_sensor_anomalies()
    report["vision"] = vision_status()
    report["routing_plan"] = build_routing_plan(report["findings"])
    return report


class AnomalyVerifyRequest(BaseModel):
    findings: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "本地筛查"
    refresh: bool = False


@app.post("/api/v1/anomalies/verify")
async def verify_sensor_anomalies(payload: AnomalyVerifyRequest | None = None) -> dict[str, Any]:
    if payload and payload.findings:
        findings = payload.findings
        source = payload.source
    else:
        findings = detect_sensor_anomalies()["findings"]
        source = "本地传感器历史筛查"
    if not findings:
        return {"status": "ok", "submitted": False, "reply": "本地没有需要上报的异常。", "findings": []}
    review = await _ask_moma(_verification_messages(findings, source))
    return {"status": "ok", "submitted": True, "findings": findings, **review}


def _route_lock_for_call() -> asyncio.Lock:
    global _route_lock
    if _route_lock is None:
        _route_lock = asyncio.Lock()
    return _route_lock


def _load_route_cache() -> None:
    try:
        raw = json.loads(_ROUTE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict) and value.get("reply"):
            _ROUTE_CACHE[key] = value


def _persist_route_cache() -> None:
    try:
        _ROUTE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ROUTE_CACHE_PATH.write_text(
            json.dumps(_ROUTE_CACHE, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        return


def _store_route_cache(cache_key: str, result: dict[str, Any]) -> None:
    if len(_ROUTE_CACHE) >= _ROUTE_CACHE_LIMIT:
        _ROUTE_CACHE.pop(next(iter(_ROUTE_CACHE)))
    _ROUTE_CACHE[cache_key] = result
    _persist_route_cache()


async def _warm_demo_route() -> None:
    try:
        result = await route_sensor_anomalies(None)
        if result.get("pending"):
            jobs = [job for job in _ROUTE_JOBS.values() if not job.done()]
            if jobs:
                await asyncio.gather(*jobs)
            result = await route_sensor_anomalies(None)
    except Exception as exc:
        print(f"MoMA demo route skipped: {exc}", flush=True)
        return
    if result.get("cached") or result.get("reply"):
        state = "ready"
    else:
        state = "empty"
    print(f"MoMA demo route {state}", flush=True)


def _route_cache_key(findings: list[dict[str, Any]]) -> str:
    compact = []
    for finding in findings:
        compact.append({"kind": finding.get("kind"), **_compact_finding(finding)})
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


@app.post("/api/v1/anomalies/route")
async def route_sensor_anomalies(payload: AnomalyVerifyRequest | None = None) -> dict[str, Any]:
    findings = payload.findings if payload and payload.findings else detect_sensor_anomalies()["findings"]
    plan = build_routing_plan(findings)
    if not plan:
        return {"status": "ok", "submitted": False, "routes": [], "fusion": None, "reply": "没有需要路由的异常。"}

    cache_key = _route_cache_key(findings)
    refresh = bool(payload and payload.refresh)
    async with _route_lock_for_call():
        cached = _ROUTE_CACHE.get(cache_key)
        if cached and not refresh:
            return {**cached, "cached": True, "pending": False}
        if refresh:
            _ROUTE_CACHE.pop(cache_key, None)
            _ROUTE_ERRORS.pop(cache_key, None)
        elif cache_key in _ROUTE_ERRORS:
            return _ROUTE_ERRORS[cache_key]
        job = _ROUTE_JOBS.get(cache_key)
        if job is not None and not job.done():
            return _pending_route_result(plan)
        _ROUTE_JOBS[cache_key] = asyncio.create_task(_finish_demo_route(cache_key, findings, plan))
        return _pending_route_result(plan)


def _pending_route_result(plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "ok",
        "submitted": True,
        "pending": True,
        "cached": False,
        "routes": [{**item, "status": "pending", "reply": "正在调用"} for item in plan],
        "fusion": None,
        "reply": "",
        "note": "各类正在分别调用。演示先显示备用结论，返回后自动替换。",
    }


async def _review_category(item: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    group = [finding for finding in findings if _category_of(finding)[0] == item["category"]]
    try:
        review = await _ask_moma(
            _category_route_messages(item, group),
            item["strategy"],
            item["max_tokens"],
            timeout=_ROUTE_CALL_TIMEOUT,
        )
    except HTTPException as exc:
        return {**item, "status": "error", "detail": str(exc.detail), "reply": ""}
    return {**item, "status": "ok", **review}


async def _finish_demo_route(
    cache_key: str,
    findings: list[dict[str, Any]],
    plan: list[dict[str, Any]],
) -> None:
    routes = list(await asyncio.gather(*[_review_category(item, findings) for item in plan]))
    reply = _merge_route_replies(routes)
    if reply:
        fusion = {
            "status": "ok",
            "category": "合并复核",
            "strategy_label": "分类汇总",
            "task_label": MOMA_TASKS["review"]["label"],
            "reason": "每类单独短调用，这里汇总各类可见结论",
            "model": "、".join(dict.fromkeys(str(route.get("model") or "") for route in routes if route.get("model"))),
            "reply": reply,
        }
    else:
        fusion = {
            "status": "error",
            "category": "合并复核",
            "strategy_label": "分类汇总",
            "task_label": MOMA_TASKS["review"]["label"],
            "detail": "MoMA 没有形成可展示的复核结论。",
            "reply": "",
        }
    result = {
        "status": "ok",
        "submitted": True,
        "pending": False,
        "cached": False,
        "routes": routes,
        "fusion": fusion,
        "reply": reply,
        "note": "每类单独调用。结论需要人工确认。",
    }
    if reply:
        _ROUTE_ERRORS.pop(cache_key, None)
        _store_route_cache(cache_key, result)
    else:
        _ROUTE_ERRORS[cache_key] = result


@app.get("/api/v1/videos/detections")
async def video_detections(video: str | None = None) -> dict[str, Any]:
    return await run_in_threadpool(load_video_detections, video)


@app.post("/api/v1/anomalies/video")
async def verify_video_anomalies(video: str | None = None) -> dict[str, Any]:
    report = await run_in_threadpool(scan_local_video, video)
    report["offline_review"] = OFFLINE_REVIEW
    report["routing_plan"] = build_routing_plan(report.get("findings") or [])
    report["submitted"] = False
    if report.get("status") == "ok" and not report.get("findings"):
        report["reply"] = "与播放器相同的检测结果里，没有需要上报的停驶、人员或两轮车。"
    return report


@app.get("/api/v1/moma/status")
async def moma_status() -> dict[str, Any]:
    client = MomaChatClient()
    missing = [
        name
        for name, value in (
            ("MOMA_CHAT_COMPLETIONS_URL", client.endpoint),
            ("MOMA_MODEL", client.model),
            ("MOMA_API_KEY", client.api_key),
        )
        if not value
    ]
    return {
        "configured": not missing,
        "missing": missing,
        "model": client.model or None,
        "timeout_seconds": client.timeout,
        "strategies": [{"id": key, "label": item["label"]} for key, item in MOMA_STRATEGIES.items()],
        "tasks": [{"id": key, "label": item["label"]} for key, item in MOMA_TASKS.items()],
    }


def prepare_moma_turn(payload: MomaAnalysisRequest) -> dict[str, Any]:
    if payload.metric not in METRICS:
        raise HTTPException(status_code=422, detail="metric must be one of CO, VI, LA, WS")

    strategy = MOMA_STRATEGIES[payload.strategy]
    task = MOMA_TASKS[payload.task]
    meta = {
        "metric": payload.metric,
        "station": payload.station,
        "task": payload.task,
        "strategy": payload.strategy,
    }
    stored = _MOMA_SESSIONS.get(payload.session_id) if payload.session_id else None
    if payload.session_id and stored is None:
        raise HTTPException(status_code=409, detail="分析会话已结束，请重新提交")
    if stored and stored["meta"] != meta:
        raise HTTPException(status_code=409, detail="测点或路由策略已变化，请重新提交")

    if stored:
        question = (payload.question or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="追问需要填写问题")
        messages = _trim_moma_messages([*stored["messages"], {"role": "user", "content": question}])
        reused = True
        sensor_window = stored["counts"]["sensor_records"]
        fault_window = stored["counts"]["fault_records"]
    else:
        metric_records = list(get_environment_records(payload.metric))
        if payload.station:
            metric_records = [record for record in metric_records if record["station"] == payload.station]
        if not metric_records:
            raise HTTPException(status_code=404, detail="所选测点没有可分析的历史记录")

        all_faults = list(get_site_faults())
        recent_records = metric_records[-task["sensor_limit"] :]
        recent_faults = all_faults[: task["fault_limit"]]
        context = {
            "tunnel": "色尔岗曲隧道",
            "data_notice": "以下均为历史参考资料，传感器记录时间为 2026 年 6 月，不代表实时状态。",
            "task": task["label"],
            "strategy": strategy["label"],
            "metric": {"code": payload.metric, "label": METRICS[payload.metric]["label"]},
            "station": payload.station or "全部测点",
            "sensor_record_count": len(metric_records),
            "recent_sensor_records": recent_records,
            "site_fault_summary": {
                "total": len(all_faults),
                "unresolved": sum(not event["recovered"] for event in all_faults),
                "recent_records": recent_faults,
            },
            "question": (payload.question or "").strip() or "请概括当前选择测点的历史数据特征，并给出需要人工复核的事项。",
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是隧道数据分析助手。只根据给定的历史记录和本会话快照回答，不要把历史记录说成实时状态，不要编造阈值或告警。"
                    "信息不足就写无法判定风险等级。直接给出结论，不要输出思考过程。"
                    f"{task['instruction']}{strategy['style']}"
                ),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        reused = False
        sensor_window = len(recent_records)
        fault_window = len(recent_faults)

    return {
        "messages": messages,
        "meta": meta,
        "strategy": strategy,
        "task": task,
        "reused": reused,
        "sensor_window": sensor_window,
        "fault_window": fault_window,
    }


def _analysis_result(
    payload: MomaAnalysisRequest,
    prepared: dict[str, Any],
    *,
    model: str,
    answer: str,
    usage: Any,
    elapsed_ms: int,
) -> dict[str, Any]:
    messages = [*prepared["messages"], {"role": "assistant", "content": answer}]
    session_id = payload.session_id or str(uuid.uuid4())
    _remember_moma_session(
        session_id,
        messages,
        prepared["meta"],
        {"sensor_records": prepared["sensor_window"], "fault_records": prepared["fault_window"]},
    )
    return {
        "status": "ok",
        "model": model,
        "reply": answer,
        "usage": compact_moma_usage(usage),
        "elapsed_ms": elapsed_ms,
        "session_id": session_id,
        "turn": sum(message["role"] == "user" for message in messages),
        "strategy": {"id": payload.strategy, "label": prepared["strategy"]["label"]},
        "task": {"id": payload.task, "label": prepared["task"]["label"]},
        "context": {
            "metric": payload.metric,
            "station": payload.station,
            "sensor_records": prepared["sensor_window"],
            "fault_records": prepared["fault_window"],
            "historical": True,
            "reused": prepared["reused"],
        },
    }


def _moma_http_error(response: dict[str, Any]) -> HTTPException:
    detail = response.get("detail", "")
    if "not configured" in detail:
        status_code = 503
    elif "timed out" in detail.lower() or "timeout" in detail.lower():
        status_code = 504
    else:
        status_code = 502
    return HTTPException(status_code=status_code, detail=detail)


async def collect_moma_analysis(payload: MomaAnalysisRequest) -> dict[str, Any]:
    prepared = prepare_moma_turn(payload)
    strategy = prepared["strategy"]
    client = MomaChatClient()
    started = time.perf_counter()
    response = await run_in_threadpool(
        client.chat_completion,
        prepared["messages"],
        max_tokens=strategy["max_tokens"],
        temperature=strategy["temperature"],
        top_p=strategy["top_p"],
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.get("status") == "error":
        raise _moma_http_error(response)

    try:
        raw_answer = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="MoMA 返回中未找到聊天补全内容") from exc
    answer = visible_moma_reply(raw_answer)
    if not answer:
        raise HTTPException(
            status_code=502,
            detail="MoMA 路由到的模型把本次输出额度用在推理过程，没有形成可展示的结论。请改用效果优先后重新提交。",
        )
    return _analysis_result(
        payload,
        prepared,
        model=response.get("model") or client.model,
        answer=answer,
        usage=response.get("usage"),
        elapsed_ms=elapsed_ms,
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/v1/moma/analyze")
async def analyze_with_moma(payload: MomaAnalysisRequest) -> StreamingResponse:
    prepared = prepare_moma_turn(payload)
    strategy = prepared["strategy"]

    async def events():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        client = MomaChatClient()
        started = time.perf_counter()

        def worker() -> None:
            try:
                for event in client.iter_chat(
                    prepared["messages"],
                    max_tokens=strategy["max_tokens"],
                    temperature=strategy["temperature"],
                    top_p=strategy["top_p"],
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "detail": str(exc)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "end"})

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                event = await queue.get()
                event_type = event.get("type")
                if event_type == "end":
                    break
                if event_type == "delta" and event.get("text"):
                    yield _sse({"type": "delta", "text": event["text"]})
                elif event_type == "error":
                    yield _sse({"type": "error", "detail": event.get("detail") or "MoMA 调用失败"})
                    return
                elif event_type == "result":
                    answer = visible_moma_reply(event.get("content") or "")
                    if not answer:
                        yield _sse({
                            "type": "error",
                            "detail": "MoMA 路由到的模型把本次输出额度用在推理过程，没有形成可展示的结论。请改用效果优先后重新提交。",
                        })
                        return
                    result = _analysis_result(
                        payload,
                        prepared,
                        model=event.get("model") or client.model,
                        answer=answer,
                        usage=event.get("usage"),
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
                    yield _sse({"type": "done", **result})
        finally:
            await worker_task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=False)
