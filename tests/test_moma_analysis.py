import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from api_server import (
    AnomalyVerifyRequest,
    MomaAnalysisRequest,
    _MOMA_SESSIONS,
    analyze_with_moma,
    collect_moma_analysis,
    _ROUTE_CACHE,
    _ROUTE_ERRORS,
    _ROUTE_JOBS,
    build_routing_plan,
    moma_status,
    reset_moma_sessions,
    route_sensor_anomalies,
    visible_moma_reply,
)


class MomaAnalysisApiTests(unittest.TestCase):
    def setUp(self):
        reset_moma_sessions()

    def test_analysis_sends_historical_sensor_and_fault_context(self):
        mock_client = unittest.mock.Mock()
        mock_client.model = "endpoint-test"
        mock_client.chat_completion.return_value = {
            "model": "endpoint-test",
            "choices": [{"message": {"content": "需人工复核历史趋势。"}}],
            "usage": {"total_tokens": 30},
        }
        payload = MomaAnalysisRequest(metric="CO", station="YK921+055")

        with patch("api_server.MomaChatClient", return_value=mock_client):
            result = asyncio.run(collect_moma_analysis(payload))

        messages = mock_client.chat_completion.call_args.args[0]
        context = json.loads(messages[1]["content"])
        self.assertEqual(result["model"], "endpoint-test")
        self.assertEqual(result["reply"], "需人工复核历史趋势。")
        self.assertTrue(result["context"]["historical"])
        self.assertEqual(context["station"], "YK921+055")
        self.assertEqual(context["sensor_record_count"], 46)
        self.assertEqual(len(context["recent_sensor_records"]), 8)
        self.assertEqual(context["strategy"], "均衡优先")
        self.assertIn("不代表实时状态", context["data_notice"])
        self.assertGreater(context["site_fault_summary"]["total"], 0)
        self.assertEqual(mock_client.chat_completion.call_args.kwargs["max_tokens"], 384)
        self.assertEqual(mock_client.chat_completion.call_args.kwargs["temperature"], 0.2)

    def test_follow_up_reuses_the_same_snapshot(self):
        mock_client = unittest.mock.Mock()
        mock_client.model = "endpoint-test"
        mock_client.chat_completion.side_effect = [
            {"model": "endpoint-test", "choices": [{"message": {"content": "首次结论"}}], "usage": {"total_tokens": 20}},
            {"model": "endpoint-test", "choices": [{"message": {"content": "追问结论"}}], "usage": {"total_tokens": 8}},
        ]
        first = MomaAnalysisRequest(metric="CO", station="YK921+055", strategy="cost", task="patrol")

        with patch("api_server.MomaChatClient", return_value=mock_client):
            created = asyncio.run(collect_moma_analysis(first))
            followed = asyncio.run(
                collect_moma_analysis(
                    MomaAnalysisRequest(
                        metric="CO",
                        station="YK921+055",
                        strategy="cost",
                        task="patrol",
                        session_id=created["session_id"],
                        question="未恢复故障和这次读数有没有同时出现？",
                    )
                )
            )

        second_messages = mock_client.chat_completion.call_args_list[1].args[0]
        user_messages = [message["content"] for message in second_messages if message["role"] == "user"]
        self.assertEqual(followed["reply"], "追问结论")
        self.assertTrue(followed["context"]["reused"])
        self.assertEqual(followed["turn"], 2)
        self.assertEqual(len(user_messages), 2)
        self.assertIn("recent_sensor_records", user_messages[0])
        self.assertNotIn("recent_sensor_records", user_messages[1])
        self.assertEqual(mock_client.chat_completion.call_args.kwargs["max_tokens"], 256)

    def test_reasoning_trace_is_hidden_and_unfinished_trace_is_not_stored(self):
        self.assertEqual(visible_moma_reply("<think>先看数据</think>结论：读数在 0 到 5.6 之间。"), "结论：读数在 0 到 5.6 之间。")
        mock_client = unittest.mock.Mock()
        mock_client.model = "endpoint-test"
        mock_client.chat_completion.return_value = {
            "model": "endpoint-test",
            "choices": [{"message": {"content": "<think>还在推理，结论被截断"}}],
            "usage": {"total_tokens": 10},
        }

        with patch("api_server.MomaChatClient", return_value=mock_client):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(collect_moma_analysis(MomaAnalysisRequest(metric="CO", station="YK921+055", strategy="cost")))

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(_MOMA_SESSIONS, {})

    def test_expired_session_asks_for_a_new_submission(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                collect_moma_analysis(
                    MomaAnalysisRequest(
                        metric="CO",
                        station="YK921+055",
                        session_id="12345678-1234-1234-1234-123456789abc",
                        question="继续说明",
                    )
                )
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_analyze_route_streams_the_answer(self):
        def fake_iter(messages, **kwargs):
            yield {"type": "delta", "text": "结论"}
            yield {"type": "result", "model": "fast-model", "content": "结论", "usage": {"total_tokens": 4}}

        async def run():
            with patch("api_server.MomaChatClient") as ctor:
                ctor.return_value.iter_chat.side_effect = fake_iter
                response = await analyze_with_moma(
                    MomaAnalysisRequest(metric="CO", station="YK921+055", strategy="cost", task="patrol")
                )
                pieces = []
                async for chunk in response.body_iterator:
                    pieces.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(pieces)

        body = asyncio.run(run())
        self.assertIn("结论", body)
        self.assertIn('"type": "done"', body)
        self.assertIn("fast-model", body)

    def test_status_does_not_expose_the_api_key(self):
        status = asyncio.run(moma_status())
        self.assertEqual(
            set(status),
            {"configured", "missing", "model", "timeout_seconds", "strategies", "tasks"},
        )
        self.assertNotIn("api_key", json.dumps(status))

    def test_moma_read_timeout_returns_gateway_timeout(self):
        mock_client = unittest.mock.Mock()
        mock_client.chat_completion.return_value = {"status": "error", "detail": "The read operation timed out"}

        with patch("api_server.MomaChatClient", return_value=mock_client):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(collect_moma_analysis(MomaAnalysisRequest(metric="CO", station="YK921+055")))

        self.assertEqual(raised.exception.status_code, 504)

    def test_demo_findings_use_three_strategies_and_fusion(self):
        findings = [
            {"kind": "co_high", "label": "一氧化碳", "simulated": True, "detail": "模拟"},
            {"kind": "light_drop", "label": "照度", "simulated": True, "detail": "模拟"},
            {"kind": "temperature_high", "label": "温度", "simulated": True, "detail": "模拟"},
            {"kind": "vehicle_stop", "label": "车辆停驶", "simulated": True, "detail": "模拟"},
        ]
        plan = {item["category"]: item for item in build_routing_plan(findings)}
        self.assertEqual(plan["一氧化碳"]["strategy"], "balanced")
        self.assertEqual(plan["照度"]["strategy"], "cost")
        self.assertEqual(plan["温度"]["strategy"], "cost")
        self.assertEqual(plan["车辆停驶"]["strategy"], "quality")
        self.assertLess(plan["照度"]["max_tokens"], plan["车辆停驶"]["max_tokens"])

        calls = []
        _ROUTE_CACHE.clear()
        _ROUTE_ERRORS.clear()
        _ROUTE_JOBS.clear()

        async def fake_ask(messages, strategy_id="balanced", max_tokens=None, timeout=None):
            calls.append((strategy_id, max_tokens, messages[1]["content"], timeout))
            return {"model": f"router-{strategy_id}", "reply": f"{strategy_id} 模拟结论", "usage": {"total_tokens": 12}, "elapsed_ms": 8}

        request = AnomalyVerifyRequest(findings=findings)

        async def run_twice():
            first = await route_sensor_anomalies(request)
            job = next(iter(_ROUTE_JOBS.values()))
            await job
            second = await route_sensor_anomalies(request)
            return first, second

        with patch("api_server._persist_route_cache"), patch("api_server._ask_moma", side_effect=fake_ask):
            result, cached = asyncio.run(run_twice())

        self.assertTrue(result["submitted"])
        self.assertTrue(result["pending"])
        self.assertFalse(result["cached"])
        self.assertEqual([call[0] for call in calls], ["balanced", "cost", "cost", "quality"])
        self.assertEqual([call[1] for call in calls], [512, 448, 448, 640])
        self.assertTrue(all(call[3] == 45 for call in calls))
        self.assertEqual([call[2] for call in calls], ["一氧化碳 ｜模拟", "照度 ｜模拟", "温度 ｜模拟", "车辆停驶 ｜模拟"])
        self.assertTrue(all(item["status"] == "pending" for item in result["routes"]))
        self.assertIsNone(result["fusion"])
        self.assertEqual(cached["fusion"]["status"], "ok")
        self.assertIn("一氧化碳：balanced 模拟结论", cached["reply"])
        self.assertIn("是否合并上报：否", cached["reply"])
        self.assertTrue(cached["cached"])
        self.assertEqual([item["model"] for item in cached["routes"]], ["router-balanced", "router-cost", "router-cost", "router-quality"])


if __name__ == "__main__":
    unittest.main()
