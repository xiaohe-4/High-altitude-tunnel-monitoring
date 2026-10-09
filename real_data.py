from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from zipfile import BadZipFile

import openpyxl
import xlrd
from openpyxl.utils.exceptions import InvalidFileException


ROOT = Path(__file__).resolve().parent
TRUE_DATA_DIR = ROOT / "data" / "true_data"
TUNNEL_NAME = "色尔岗曲隧道"

METRICS = {
    "CO": {"label": "CO 浓度", "file": "环境/环境数据表 (日).xls"},
    "VI": {"label": "能见度", "file": "环境/环境数据表 (日).xls"},
    "LA": {"label": "光照", "file": "环境/环境数据表 光照数据（周）.xls"},
    "WS": {"label": "风速", "file": "环境/环境数据表.风速风向xls.xls"},
}
FAULT_FILE = "设备/故障分析记录表（月）.xls"
REFERENCE_CATEGORIES = {
    "环境": "环境监测",
    "事件": "事件统计",
    "设备": "设备记录",
    "通信": "通信与报警",
    "照明": "照明控制",
    "报告": "运行报告",
}


def iter_workbook_rows(path: Path) -> Iterable[tuple[Any, ...]]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile):
        workbook_xls = xlrd.open_workbook(path, on_demand=True)
        try:
            sheet = workbook_xls.sheet_by_index(0)
            for row_index in range(sheet.nrows):
                yield tuple(sheet.row_values(row_index))
        finally:
            workbook_xls.release_resources()
    else:
        try:
            for row in workbook.worksheets[0].iter_rows(values_only=True):
                yield tuple(row)
        finally:
            workbook.close()


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%a %b %d %H:%M:%S CST %Y")
    except ValueError:
        return text
    return parsed.isoformat(sep=" ", timespec="seconds")


def parse_sensor_rows(rows: Iterable[tuple[Any, ...]], metric: str) -> list[dict[str, Any]]:
    iterator = iter(rows)
    header = next(iterator, None)
    if not header:
        return []

    columns = {str(name).strip(): index for index, name in enumerate(header) if name is not None}
    required = ("设备名称", "路段/隧道", "桩号", "类型", "数值", "记录时间")
    if any(name not in columns for name in required):
        return []

    result = []
    for row in iterator:
        try:
            if str(row[columns["路段/隧道"]]).strip() != TUNNEL_NAME:
                continue
            if str(row[columns["类型"]]).strip() != metric:
                continue
            value = float(row[columns["数值"]])
            if not isfinite(value):
                continue
            result.append(
                {
                    "metric": metric,
                    "station": str(row[columns["桩号"]]).strip(),
                    "device": str(row[columns["设备名称"]]).strip(),
                    "timestamp": _timestamp(row[columns["记录时间"]]),
                    "value": value,
                }
            )
        except (IndexError, TypeError, ValueError):
            continue
    result.sort(key=lambda item: item["timestamp"])
    return result


@lru_cache(maxsize=4)
def get_environment_records(metric: str) -> tuple[dict[str, Any], ...]:
    config = METRICS.get(metric)
    if config is None:
        return ()
    path = TRUE_DATA_DIR / config["file"]
    if not path.is_file():
        return ()
    return tuple(parse_sensor_rows(iter_workbook_rows(path), metric))


def parse_fault_rows(rows: Iterable[tuple[Any, ...]]) -> list[dict[str, Any]]:
    iterator = iter(rows)
    header = next(iterator, None)
    if not header:
        return []

    columns = {str(name).strip(): index for index, name in enumerate(header) if name is not None}
    required = (
        "设备名称",
        "设备故障码",
        "故障时间",
        "故障信息",
        "故障标识:0-故障 1-故障恢复",
        "路段名称",
        "故障恢复时间",
        "分类名称",
        "桩号",
    )
    if any(name not in columns for name in required):
        return []

    result = []
    for row in iterator:
        try:
            if str(row[columns["路段名称"]]).strip() != TUNNEL_NAME:
                continue
            recovered = str(row[columns["故障标识:0-故障 1-故障恢复"]]).strip() == "1"
            result.append(
                {
                    "device": str(row[columns["设备名称"]]).strip(),
                    "code": str(row[columns["设备故障码"]]).strip(),
                    "time": _timestamp(row[columns["故障时间"]]),
                    "description": str(row[columns["故障信息"]]).strip(),
                    "recovered": recovered,
                    "recovered_at": _timestamp(row[columns["故障恢复时间"]]) if recovered else "",
                    "category": str(row[columns["分类名称"]]).strip(),
                    "station": str(row[columns["桩号"]]).strip(),
                }
            )
        except IndexError:
            continue
    result.sort(key=lambda item: item["time"], reverse=True)
    return result


@lru_cache(maxsize=1)
def get_site_faults() -> tuple[dict[str, Any], ...]:
    path = TRUE_DATA_DIR / FAULT_FILE
    if not path.is_file():
        return ()
    return tuple(parse_fault_rows(iter_workbook_rows(path)))


def _file_entry(path: Path, category: str) -> dict[str, Any]:
    relative = path.relative_to(ROOT).as_posix()
    return {
        "name": path.name,
        "category": category,
        "size_bytes": path.stat().st_size,
        "url": "/".join(quote(part) for part in relative.split("/")),
    }


def list_data_files() -> list[dict[str, Any]]:
    files = []
    if TRUE_DATA_DIR.is_dir():
        for path in sorted(TRUE_DATA_DIR.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            category = REFERENCE_CATEGORIES.get(path.parent.name, "参考数据")
            files.append(_file_entry(path, category))
    video_dir = ROOT / "data" / "videos"
    if video_dir.is_dir():
        for path in sorted(video_dir.iterdir()):
            if not path.is_file() or path.name == ".gitkeep" or path.name.endswith(".detections.json"):
                continue
            files.append(_file_entry(path, "视频"))
    return files