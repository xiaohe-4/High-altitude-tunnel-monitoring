from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from real_data import ROOT


VIDEO_DIR = ROOT / "data" / "videos"
DEMO_VIDEO_NAME = "车辆停驶故障_演示.mp4"
WATCHED_CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
VEHICLE_CLASSES = {"car", "bus", "truck"}
ABNORMAL_CLASSES = {"person", "bicycle", "motorcycle"}
CLASS_LABELS = {
    "person": "行人",
    "bicycle": "自行车",
    "car": "汽车",
    "motorcycle": "摩托车",
    "bus": "公交",
    "truck": "货车",
}
_MODEL = None


def vision_status() -> dict[str, Any]:
    try:
        import cv2  # noqa: F401
        from ultralytics import YOLO  # noqa: F401
    except ImportError:
        return {
            "ready": False,
            "detail": "未安装 ultralytics 或 opencv，本地视频检测暂不可用。传感器筛查不依赖这两项。",
        }
    video = _video_path()
    if video is None:
        return {"ready": False, "detail": "data/videos 中没有 MP4 文件。"}
    return {"ready": True, "video": video.name}


def _video_files() -> list[Path]:
    if not VIDEO_DIR.is_dir():
        return []
    return sorted(path for path in VIDEO_DIR.glob("*.mp4") if not path.name.endswith(".detections.mp4"))


def _video_path(video_name: str | None = None) -> Path | None:
    videos = _video_files()
    if video_name:
        if Path(video_name).name != video_name:
            return None
        return next((path for path in videos if path.name == video_name), None)
    demo = next((path for path in videos if path.name == DEMO_VIDEO_NAME), None)
    return demo or (videos[0] if videos else None)


def stationary_vehicle(samples: list[dict[str, Any]]) -> dict[str, Any] | None:
    present = []
    for sample in samples:
        vehicles = [box for box in sample.get("boxes", []) if box.get("class_name") in VEHICLE_CLASSES]
        if not vehicles:
            continue
        box = max(vehicles, key=lambda item: (item["x2"] - item["x1"]) * (item["y2"] - item["y1"]))
        present.append((float(sample["time"]), box))

    for start, _ in enumerate(present):
        window = present[start:]
        if len(window) < 4:
            break
        duration = window[-1][0] - window[0][0]
        if duration < 3:
            break
        centers_x = [(box["x1"] + box["x2"]) / 2 for _, box in window]
        centers_y = [(box["y1"] + box["y2"]) / 2 for _, box in window]
        if max(centers_x) - min(centers_x) <= 0.04 and max(centers_y) - min(centers_y) <= 0.04:
            box = window[-1][1]
            return {
                "duration": round(duration, 1),
                "label": box.get("label") or CLASS_LABELS.get(box["class_name"], box["class_name"]),
                "class_name": box["class_name"],
            }
    return None


def _inference_kwargs(video: Path) -> dict[str, Any]:
    if video.name == DEMO_VIDEO_NAME:
        return {"conf": 0.35, "imgsz": 640, "verbose": False}
    return {"conf": 0.35, "imgsz": 480, "verbose": False}


def _model():
    global _MODEL
    if _MODEL is None:
        from ultralytics import YOLO

        _MODEL = YOLO("yolov8n.pt")
    return _MODEL


def _cache_path(video: Path) -> Path:
    return video.with_suffix(".detections.json")


def load_video_detections(video_name: str | None = None) -> dict[str, Any]:
    if video_name and Path(video_name).name != video_name:
        return {"status": "error", "ready": False, "detail": "视频名称无效", "samples": []}

    status = vision_status()
    if not status["ready"]:
        return {"status": "unavailable", **status, "samples": []}

    video = _video_path(video_name)
    if video is None:
        detail = "未找到该视频" if video_name else "data/videos 中没有 MP4 文件。"
        return {"status": "error", "ready": False, "detail": detail, "samples": []}
    cache = _cache_path(video)
    if cache.is_file() and cache.stat().st_mtime >= video.stat().st_mtime:
        return json.loads(cache.read_text(encoding="utf-8"))

    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return {"status": "error", "ready": False, "detail": f"无法打开视频 {video.name}", "samples": []}

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    step = 3
    model = _model()
    samples = []

    for frame_index in range(0, max(frame_count, 1), step):
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            break
        result = model(frame, **_inference_kwargs(video))[0]
        boxes = []
        for box in result.boxes:
            name = result.names[int(box.cls[0])]
            if name not in WATCHED_CLASSES or width <= 0 or height <= 0:
                continue
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            boxes.append(
                {
                    "label": CLASS_LABELS.get(name, name),
                    "class_name": name,
                    "confidence": round(float(box.conf[0]), 2),
                    "x1": round(x1 / width, 4),
                    "y1": round(y1 / height, 4),
                    "x2": round(x2 / width, 4),
                    "y2": round(y2 / height, 4),
                }
            )
        samples.append({"time": round(frame_index / fps, 3), "boxes": boxes})

    capture.release()
    payload = {
        "status": "ok",
        "ready": True,
        "video": video.name,
        "width": width,
        "height": height,
        "fps": fps,
        "hold_seconds": round(step / fps, 3),
        "samples": samples,
    }
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def findings_from_detections(detection: dict[str, Any]) -> list[dict[str, Any]]:
    video_name = str(detection.get("video") or "本地视频")
    simulated = "演示" in video_name
    findings = []
    seen = set()
    for sample in detection.get("samples") or []:
        counts: dict[str, int] = {}
        for box in sample.get("boxes") or []:
            name = box.get("class_name")
            if name in WATCHED_CLASSES:
                counts[name] = counts.get(name, 0) + 1
        vehicles = sum(counts.get(name, 0) for name in VEHICLE_CLASSES)
        stamp = f"{sample.get('time', 0)} 秒"
        for name in sorted(ABNORMAL_CLASSES & counts.keys()):
            key = f"class-{name}"
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "id": f"video-{name}-{sample.get('time', 0)}",
                    "kind": "video_object",
                    "label": "隧道画面出现人员" if name == "person" else "隧道画面出现两轮车",
                    "station": "本地视频",
                    "timestamp": stamp,
                    "value": counts[name],
                    "baseline": "与播放器相同的 YOLOv8n 检测结果，未做轨迹跟踪",
                    "detail": f"在 {video_name} 的检测结果中识别到 {name} {counts[name]} 个。这只说明画面里有该类目标。",
                    "simulated": simulated,
                }
            )
        if vehicles >= 4 and "dense-vehicles" not in seen:
            seen.add("dense-vehicles")
            findings.append(
                {
                    "id": f"video-dense-{sample.get('time', 0)}",
                    "kind": "video_dense",
                    "label": "同一画面车辆较多",
                    "station": "本地视频",
                    "timestamp": stamp,
                    "value": vehicles,
                    "baseline": "单帧机动车数量达到 4",
                    "detail": "未跟踪车速和停车时长，不能把车辆较多直接当成停车或拥堵。",
                    "simulated": simulated,
                }
            )

    stopped = stationary_vehicle(detection.get("samples") or [])
    if stopped:
        findings.insert(
            0,
            {
                "id": f"video-stop-{video_name}",
                "kind": "vehicle_stop",
                "label": "车辆停驶",
                "station": "K922+065" if simulated else "本地视频",
                "timestamp": f"约 {stopped['duration']} 秒内位置基本不变",
                "value": stopped["duration"],
                "unit": "秒",
                "baseline": "同一车辆框中心的位移不超过画面宽度的 4%",
                "detail": "模拟演示：画面中的车辆持续停在车道内。" if simulated else "检测框中心几乎不动，疑似停驶，需人工确认。",
                "simulated": simulated,
            },
        )
    return findings


def scan_local_video(video_name: str | None = None) -> dict[str, Any]:
    detection = load_video_detections(video_name)
    if detection.get("status") != "ok":
        return {**detection, "findings": [], "submitted": False}
    return {
        "status": "ok",
        "ready": True,
        "video": detection.get("video"),
        "sampled_frames": len(detection.get("samples") or []),
        "source": "detection_cache",
        "submitted": False,
        "findings": findings_from_detections(detection),
        "notes": ["停驶判断与播放器使用同一份 YOLO 检测结果。本次不调用 MoMA，也不上传原始视频。"],
    }
