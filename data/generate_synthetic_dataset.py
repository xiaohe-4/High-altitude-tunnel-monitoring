import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "tunnel_day_dataset.json"


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def generate_dataset() -> dict:
    start = datetime(2026, 9, 20, 0, 0, 0)
    end = start + timedelta(days=1)

    cameras = [
        {"point_id": "K920+765", "location": "入口枪机", "direction": "R", "lane": "入口车道", "resolution": "704x576"},
        {"point_id": "K922+065", "location": "右线中段", "direction": "R", "lane": "中段车道", "resolution": "704x576"},
        {"point_id": "K924+165", "location": "出口枪机", "direction": "R", "lane": "出口车道", "resolution": "704x576"},
    ]

    sensor_series = []
    current = start
    while current < end:
        base_temp = 9.5 + 7.8 * (1 + ((current.hour + current.minute / 60.0) / 24.0))
        temp = round(base_temp + 0.8 * __import__("math").sin(current.hour / 2.5), 2)
        humidity = round(54 + 16 * __import__("math").sin((current.hour - 6) / 4.5), 2)
        co = 2.1 + ((current.hour - 12) ** 2) / 250.0
        if 18 <= current.hour <= 22:
            co += 1.6
        if current.hour in (6, 7, 8):
            co += 0.7
        co = round(max(0.0, co), 2)

        ventilation = "正常"
        if current.hour in (1, 2, 3, 4, 5):
            ventilation = "低速"
        elif current.hour in (18, 19, 20, 21):
            ventilation = "高负荷"

        for camera in cameras:
            sensor_series.append({
                "timestamp": iso(current),
                "point_id": camera["point_id"],
                "location": camera["location"],
                "temperature_c": temp,
                "humidity_pct": round(max(35.0, min(80.0, humidity)), 2),
                "co_ppm": round(co + (0.1 if camera["point_id"] == "K924+165" else 0.0), 2),
                "ventilation_status": ventilation,
                "power_status": "正常",
                "data_quality": "良好",
                "lane_load": round(0.42 + 0.35 * __import__("math").sin(current.hour / 4.0 + len(camera["point_id"])), 2),
            })
        current += timedelta(minutes=5)

    image_events = [
        {
            "event_id": "EV-20260920-014",
            "point_id": "K922+065",
            "event_type": "parking_candidate",
            "risk_level": "L2",
            "start_time": "2026-09-20T09:42:00",
            "end_time": "2026-09-20T09:58:40",
            "duration_sec": 1000,
            "avg_speed_px_s": 3.4,
            "anomaly_reason": "中段车道停靠时间超过确认阈值",
            "confidence": 0.82,
            "status": "待复核",
            "object_type": "车辆",
            "object_id": "track_088",
            "evidence_chain": [
                {"type": "video_frame", "path": "/evidence/K922+065/20260920_094200.jpg"},
                {"type": "trajectory", "id": "track_088"},
                {"type": "device_log", "id": "log_K922+065_20260920"}
            ],
            "actions": ["提高核查顺序", "调取同期CO时序", "确认通风设备状态"]
        },
        {
            "event_id": "EV-20260920-009",
            "point_id": "K924+165",
            "event_type": "device_log_abnormal",
            "risk_level": "L1",
            "start_time": "2026-09-20T11:05:00",
            "end_time": "2026-09-20T11:20:00",
            "duration_sec": 900,
            "avg_speed_px_s": 0,
            "anomaly_reason": "设备日志记录网络异常及视频观测中断",
            "confidence": 0.71,
            "status": "处理中",
            "object_type": "设备",
            "object_id": "dev_K924+165",
            "evidence_chain": [
                {"type": "device_log", "id": "log_K924+165_20260920"},
                {"type": "network_status", "id": "net_20260920_110500"}
            ],
            "actions": ["核查设备恢复状态", "复测出口观测完整率"]
        },
        {
            "event_id": "EV-20260920-006",
            "point_id": "K920+765",
            "event_type": "slow_passage",
            "risk_level": "L0",
            "start_time": "2026-09-20T07:34:00",
            "end_time": "2026-09-20T07:36:10",
            "duration_sec": 130,
            "avg_speed_px_s": 18.2,
            "anomaly_reason": "正常慢速通行，无真实停车特征",
            "confidence": 0.93,
            "status": "正常",
            "object_type": "车辆",
            "object_id": "track_052",
            "evidence_chain": [{"type": "trajectory", "id": "track_052"}],
            "actions": ["保持监测"]
        },
        {
            "event_id": "EV-20260920-003",
            "point_id": "环境CO",
            "event_type": "co_wave",
            "risk_level": "L1",
            "start_time": "2026-09-20T18:15:00",
            "end_time": "2026-09-20T18:45:00",
            "duration_sec": 1800,
            "avg_speed_px_s": 0,
            "anomaly_reason": "CO浓度在分段时间内上涨，与通风设备高负荷状态一致",
            "confidence": 0.77,
            "status": "已闭环",
            "object_type": "环境",
            "object_id": "sensor_co_cluster",
            "evidence_chain": [
                {"type": "sensor_series", "id": "co_series_20260920"},
                {"type": "device_log", "id": "vent_20260920"}
            ],
            "actions": ["维持通风状态监测", "继续追踪CO趋势"]
        }
    ]

    video_manifest = {
        "tunnel_id": "Sergangqu_R",
        "date": "2026-09-20",
        "site": "色尔岗曲隧道右线",
        "files": [
            {"camera_id": "K920+765", "filename": "official_k920_765_20260920.mp4", "source": "官方录像", "duration_sec": 86400, "fps": 25, "resolution": "704x576", "status": "已入库"},
            {"camera_id": "K922+065", "filename": "official_k922_065_20260920.mp4", "source": "官方录像", "duration_sec": 86400, "fps": 25, "resolution": "704x576", "status": "已入库"},
            {"camera_id": "K924+165", "filename": "official_k924_165_20260920.mp4", "source": "官方录像", "duration_sec": 86400, "fps": 25, "resolution": "704x576", "status": "已入库"}
        ],
        "annotations": {
            "roi": "隧道单车道主通行区",
            "counting_method": "YOLOv8n + ByteTrack",
            "frame_sampling_interval_sec": 5,
            "notes": "此处为官方视频清单占位，实际视频文件需由用户自行放入 data/videos/ 目录。"
        }
    }

    dataset = {
        "tunnel": {
            "tunnel_id": "Sergangqu_R",
            "tunnel_name": "色尔岗曲隧道右线",
            "altitude_m": 3100,
            "direction": "右线",
            "location": "高海拔山区",
            "date": "2026-09-20",
            "environment_note": "低温、温差大、CO波动与通风状态强相关"
        },
        "camera_points": cameras,
        "sensor_series": sensor_series,
        "events": image_events,
        "video_manifest": video_manifest,
        "risk_summary": {
            "current_risk_level": "L2",
            "risk_counts": {"L0": 18, "L1": 9, "L2": 3, "L3": 1},
            "attention_points": ["K922+065", "K924+165", "环境CO"]
        }
    }
    return dataset


if __name__ == "__main__":
    dataset = generate_dataset()
    OUTPUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Generated dataset: {OUTPUT}")
    print(f"sensor records: {len(dataset['sensor_series'])}")
    print(f"event count: {len(dataset['events'])}")
