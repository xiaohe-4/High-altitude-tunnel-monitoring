"""生成浏览器可播放的车辆停驶演示短片。成片不是现场录像。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
STILL = ROOT / "data" / "demo" / "tunnel_vehicle_fault.jpg"
SOURCE = ROOT / "data" / "videos" / "隧道实时监控.mp4"
OUTPUT = ROOT / "data" / "videos" / "车辆停驶故障_演示.mp4"
WIDTH = 1280
HEIGHT = 720
FPS = 12
APPROACH_SECONDS = 2.0
FADE_SECONDS = 0.6
HOLD_SECONDS = 7.4


def _cover(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    frame_height, frame_width = frame.shape[:2]
    scale = max(width / frame_width, height / frame_height)
    resized = cv2.resize(frame, (int(frame_width * scale), int(frame_height * scale)), interpolation=cv2.INTER_AREA)
    x = max(0, (resized.shape[1] - width) // 2)
    y = max(0, (resized.shape[0] - height) // 2)
    return resized[y : y + height, x : x + width].copy()


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _caption(frame: np.ndarray, text: str) -> np.ndarray:
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 52), fill=(12, 18, 24))
    draw.text((16, 10), text, font=_font(26), fill=(255, 196, 96))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _vehicle_box(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    from ultralytics import YOLO

    result = YOLO("yolov8n.pt")(frame, conf=0.25, imgsz=640, verbose=False)[0]
    best = None
    best_area = 0.0
    for box in result.boxes:
        name = result.names[int(box.cls[0])]
        if name not in {"car", "bus", "truck"}:
            continue
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if area > best_area:
            best_area = area
            best = (int(x1), int(y1), int(x2), int(y2))
    return best


def _blink(frame: np.ndarray, box: tuple[int, int, int, int] | None, enabled: bool) -> np.ndarray:
    if not enabled or box is None:
        return frame
    x1, y1, x2, y2 = box
    overlay = frame.copy()
    center_x = (x1 + x2) // 2
    center_y = int(y2 - (y2 - y1) * 0.16)
    cv2.circle(overlay, (center_x - 22, center_y), 9, (0, 150, 255), -1)
    cv2.circle(overlay, (center_x + 22, center_y), 9, (0, 150, 255), -1)
    return cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)


def _approach_frames() -> list[np.ndarray]:
    if not SOURCE.is_file():
        return []
    capture = cv2.VideoCapture(str(SOURCE))
    if not capture.isOpened():
        return []
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(10 * source_fps))
    step = max(1, int(round(source_fps / FPS)))
    needed = int(APPROACH_SECONDS * FPS)
    frames = []
    index = 0
    while len(frames) < needed:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            frames.append(_cover(frame, WIDTH, HEIGHT))
        index += 1
    capture.release()
    return frames


def _encode(frames: list[np.ndarray]) -> None:
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise SystemExit("请先安装 imageio-ffmpeg，再用它编码浏览器可播放的 H.264。") from exc

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-crf",
        "23",
        str(OUTPUT),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame in frames:
            process.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        process.stdin.close()
        code = process.wait()
    if code != 0:
        raise SystemExit(f"ffmpeg 编码失败，退出码 {code}")


def build() -> Path:
    if not STILL.is_file():
        raise SystemExit(f"缺少故障静帧：{STILL}")
    still = _cover(cv2.imread(str(STILL)), WIDTH, HEIGHT)
    box = _vehicle_box(still)
    approach = _approach_frames()
    if not approach:
        approach = [still]
    frames: list[np.ndarray] = []
    for frame in approach:
        frames.append(_caption(frame, "现场画面节选 · 随后切入模拟故障"))
    fade_count = int(FADE_SECONDS * FPS)
    for index in range(fade_count):
        alpha = (index + 1) / fade_count
        mixed = cv2.addWeighted(still, alpha, approach[-1], 1 - alpha, 0)
        frames.append(_caption(_blink(mixed, box, index % 6 < 3), "模拟演示 · 车辆停驶 · K922+065"))
    for index in range(int(HOLD_SECONDS * FPS)):
        frames.append(_caption(_blink(still, box, index % 6 < 3), "模拟演示 · 车辆停驶 · K922+065"))
    _encode(frames)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes, {len(frames)} frames, vehicle_box={box})")
    return OUTPUT


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    build()
    if "--with-detections" in sys.argv:
        from vision_detector import load_video_detections

        cache = load_video_detections(OUTPUT.name)
        boxes = sum(len(sample["boxes"]) for sample in cache.get("samples", []))
        print(f"detections {cache.get('status')} samples={len(cache.get('samples', []))} boxes={boxes}")
