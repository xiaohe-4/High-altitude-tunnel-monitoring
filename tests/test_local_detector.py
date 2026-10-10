import asyncio
import json
import unittest
from unittest.mock import patch

from api_server import verify_sensor_anomalies, verify_video_anomalies
from local_detector import CO_ATTENTION_PPM, detect_sensor_anomalies, field_exceedances
from vision_detector import DEMO_VIDEO_NAME, VIDEO_DIR, load_video_detections, scan_local_video, stationary_vehicle


def _vehicle(x1: float, time: float) -> dict:
    return {
        "time": time,
        "boxes": [{"class_name": "car", "label": "汽车", "x1": x1, "y1": 0.4, "x2": x1 + 0.12, "y2": 0.62}],
    }


class LocalDetectorTests(unittest.TestCase):
    def test_sensor_scan_reports_labeled_demo_events(self):
        report = detect_sensor_anomalies()

        self.assertGreater(report["scanned"]["co_records"], 0)
        self.assertGreater(report["scanned"]["vi_records"], 0)
        self.assertGreater(report["scanned"]["light_records"], 0)
        self.assertGreater(report["scanned"]["ws_records"], 0)
        self.assertEqual(report["field_findings"], [])
        self.assertEqual(report["field_check"]["attention_ppm"], CO_ATTENTION_PPM)
        self.assertTrue(report["historical"])
        self.assertTrue(report["demo"])
        self.assertIn("不作为异常", report["field_check"]["conclusion"])
        self.assertIn("没有温度序列", report["field_check"]["temperature"])
        self.assertLess(report["field_check"]["co"]["max"], 20)
        self.assertIn("演示备用结论", report["offline_review"])
        self.assertNotIn("本次云端返回。一氧化碳", report["field_check"]["conclusion"])
        kinds = {item["kind"] for item in report["findings"]}
        self.assertEqual(kinds, {"co_high", "light_drop", "temperature_high", "vehicle_stop"})
        for finding in report["findings"]:
            self.assertTrue(finding["simulated"])
            self.assertIn("模拟", finding["detail"])
        co = next(item for item in report["findings"] if item["kind"] == "co_high")
        self.assertGreater(co["value"], 14)
        temperature = next(item for item in report["findings"] if item["kind"] == "temperature_high")
        self.assertIn("温度", temperature["label"])

    def test_field_scan_flags_only_carbon_monoxide_above_attention(self):
        records = [
            {"station": "YK921+055", "timestamp": "2026-06-11 10:00:00", "value": 6.1},
            {"station": "YK921+055", "timestamp": "2026-06-11 10:15:00", "value": 86},
        ]
        found = field_exceedances(records, "CO")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["simulated"])
        self.assertEqual(found[0]["value"], 86)
        self.assertEqual(field_exceedances(records, "LA"), [])
        self.assertEqual(field_exceedances([records[0]], "CO"), [])

    def test_carbon_monoxide_zero_is_not_a_demo_event(self):
        report = detect_sensor_anomalies()
        zero_co = [item for item in report["findings"] if item["kind"] == "co_high" and item["value"] == 0]
        self.assertEqual(zero_co, [])

    def test_stationary_vehicle_requires_a_still_suffix(self):
        moving = [_vehicle(0.05 + index * 0.08, index) for index in range(6)]
        self.assertIsNone(stationary_vehicle(moving))
        held = [_vehicle(0.05 + index * 0.08, index) for index in range(3)]
        held.extend(_vehicle(0.62, 4 + index) for index in range(5))
        stopped = stationary_vehicle(held)
        self.assertIsNotNone(stopped)
        self.assertGreaterEqual(stopped["duration"], 3)

    def test_video_name_cannot_leave_the_video_directory(self):
        result = load_video_detections(r"..\隧道实时监控.mp4")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["samples"], [])

    def test_demo_video_is_preferred_when_present(self):
        if not (VIDEO_DIR / DEMO_VIDEO_NAME).is_file():
            self.skipTest("demo video not built")
        from vision_detector import _video_path

        self.assertEqual(_video_path().name, DEMO_VIDEO_NAME)

    def test_video_scan_reuses_detection_cache_and_skips_moma(self):
        samples = [_vehicle(0.62, index) for index in range(5)]
        detection = {
            "status": "ok",
            "ready": True,
            "video": DEMO_VIDEO_NAME,
            "samples": samples,
        }
        with patch("vision_detector.load_video_detections", return_value=detection):
            report = scan_local_video(DEMO_VIDEO_NAME)
        self.assertEqual(report["source"], "detection_cache")
        self.assertFalse(report["submitted"])
        self.assertEqual(report["findings"][0]["kind"], "vehicle_stop")
        self.assertTrue(report["findings"][0]["simulated"])

        with patch("api_server.scan_local_video", return_value=report):
            with patch("api_server._ask_moma") as ask:
                result = asyncio.run(verify_video_anomalies())
        ask.assert_not_called()
        self.assertFalse(result["submitted"])

    def test_empty_scan_is_not_sent_to_moma(self):
        with patch("api_server.detect_sensor_anomalies", return_value={"findings": []}):
            with patch("api_server._ask_moma") as ask:
                result = asyncio.run(verify_sensor_anomalies())
        ask.assert_not_called()
        self.assertFalse(result["submitted"])

    def test_findings_are_sent_without_temperature_claims(self):
        finding = {
            "id": "co-demo",
            "kind": "co_high",
            "label": "一氧化碳浓度偏高",
            "station": "YK921+055",
            "timestamp": "2026-06-11 10:31:42",
            "value": 6.2,
            "baseline": "同一测点历史第99百分位为 6.11",
            "detail": "待复核",
        }
        mock_answer = {"model": "endpoint-test", "reply": "疑似真实：读数处在该测点历史高位。", "usage": None, "elapsed_ms": 10}

        with patch("api_server.detect_sensor_anomalies", return_value={"findings": [finding]}):
            with patch("api_server._ask_moma", return_value=mock_answer) as ask:
                result = asyncio.run(verify_sensor_anomalies())

        payload = json.loads(ask.call_args.args[0][1]["content"])
        self.assertTrue(result["submitted"])
        self.assertEqual(result["reply"], mock_answer["reply"])
        self.assertEqual(payload["findings"][0]["station"], "YK921+055")
        self.assertNotIn("温度", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
