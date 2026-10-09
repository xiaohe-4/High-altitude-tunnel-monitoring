import unittest

from real_data import (
    TRUE_DATA_DIR,
    get_environment_records,
    get_site_faults,
    parse_fault_rows,
    parse_sensor_rows,
)


class RealDataParserTests(unittest.TestCase):
    def test_sensor_rows_are_filtered_by_tunnel_and_metric(self):
        rows = [
            ("设备名称", "路段/隧道", "桩号", "类型", "数值", "记录时间"),
            ("CO设备", "色尔岗曲隧道", "YK921+055", "CO", "5.5", "Thu Jun 11 11:16:43 CST 2026"),
            ("VI设备", "色尔岗曲隧道", "YK921+055", "VI", "0.2", "Thu Jun 11 11:16:43 CST 2026"),
            ("CO设备", "其他隧道", "YK921+055", "CO", "7.0", "Thu Jun 11 11:16:43 CST 2026"),
        ]

        records = parse_sensor_rows(rows, "CO")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["station"], "YK921+055")
        self.assertEqual(records[0]["value"], 5.5)
        self.assertEqual(records[0]["timestamp"], "2026-06-11 11:16:43")

    def test_fault_rows_preserve_recovery_state(self):
        rows = [
            ("设备名称", "设备故障码", "故障时间", "故障信息", "故障标识:0-故障 1-故障恢复", "路段名称", "故障恢复时间", "分类名称", "桩号"),
            ("摄像机1", "401", "2026-06-11T10:00:00", "设备网络异常", "1", "色尔岗曲隧道", "2026-06-11T10:05:00", "摄像机", "YK921+055"),
            ("摄像机2", "401", "2026-06-11T10:00:00", "设备网络异常", "0", "色尔岗曲隧道", "null", "摄像机", "YK922+055"),
        ]

        faults = parse_fault_rows(rows)

        recovery_by_device = {fault["device"]: fault for fault in faults}
        self.assertFalse(recovery_by_device["摄像机2"]["recovered"])
        self.assertTrue(recovery_by_device["摄像机1"]["recovered"])
        self.assertEqual(recovery_by_device["摄像机1"]["recovered_at"], "2026-06-11T10:05:00")

    @unittest.skipUnless((TRUE_DATA_DIR / "环境" / "环境数据表 (日).xls").is_file(), "真实参考表格未提供")
    def test_reads_provided_site_records(self):
        self.assertEqual(len(get_environment_records("CO")), 368)
        self.assertEqual(len(get_environment_records("VI")), 368)
        self.assertEqual(len(get_environment_records("LA")), 1344)
        self.assertEqual(len(get_environment_records("WS")), 8000)
        self.assertEqual(len(get_site_faults()), 144)


if __name__ == "__main__":
    unittest.main()