import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from moma_client import MomaChatClient


class _CaptureHandler(BaseHTTPRequestHandler):
    received = {}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        parsed = json.loads(body.decode("utf-8"))
        _CaptureHandler.received = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": parsed,
        }
        if self.path != "/v1/chat/completions":
            payload = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
            return
        asked = parsed["messages"][-1]["content"]
        answer = "<think>先看数据</think>风险等级：L1" if asked == "含思考" else "风险等级：L1"
        if parsed.get("stream"):
            chunks = [
                {"model": "sse-model", "choices": [{"delta": {"content": answer}}]},
                {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            ]
            encoded = "".join(f"data: {json.dumps(item, ensure_ascii=False)}\n\n" for item in chunks)
            encoded += "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(encoded.encode("utf-8"))
            return
        response = {
            "id": "chatcmpl-test",
            "choices": [{"message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def log_message(self, *args):
        return


class MomaChatClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_chat_completion_uses_moma_smart_route(self):
        client = MomaChatClient(
            endpoint=f"http://127.0.0.1:{self.port}/v1/chat/completions",
            api_key="demo-chat-key",
            model="endpoint-demo",
        )
        result = client.chat_completion([{"role": "user", "content": "分析这组隧道数据"}])

        self.assertEqual(result["choices"][0]["message"]["content"], "风险等级：L1")
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(_CaptureHandler.received["path"], "/v1/chat/completions")
        self.assertEqual(_CaptureHandler.received["headers"]["Authorization"], "Bearer demo-chat-key")
        self.assertEqual(_CaptureHandler.received["body"]["model"], "endpoint-demo")
        self.assertTrue(_CaptureHandler.received["body"]["stream"])
        self.assertFalse(_CaptureHandler.received["body"]["enable_thinking"])
        self.assertEqual(_CaptureHandler.received["body"]["temperature"], 0.2)
        self.assertEqual(_CaptureHandler.received["body"]["top_p"], 0.9)
        self.assertEqual(_CaptureHandler.received["body"]["max_tokens"], 256)
        self.assertEqual(result["model"], "sse-model")

    def test_stream_hides_thinking_before_the_answer(self):
        client = MomaChatClient(
            endpoint=f"http://127.0.0.1:{self.port}/v1/chat/completions",
            api_key="demo-chat-key",
            model="endpoint-demo",
        )
        result = client.chat_completion([{"role": "user", "content": "含思考"}])

        self.assertEqual(result["choices"][0]["message"]["content"], "风险等级：L1")


if __name__ == "__main__":
    unittest.main()
