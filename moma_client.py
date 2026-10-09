from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterator
from urllib import error, request

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")

_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


class _VisibleText:
    """Drop reasoning tags so the page can show answer text as it arrives."""

    def __init__(self) -> None:
        self._pending = ""
        self._skipping = False

    def push(self, text: str) -> str:
        if not text:
            return ""
        self._pending += text
        visible: list[str] = []
        while self._pending:
            if self._skipping:
                close = _THINK_CLOSE.search(self._pending)
                if close is None:
                    self._pending = self._pending[-8:]
                    break
                self._pending = self._pending[close.end() :]
                self._skipping = False
                continue
            open_tag = _THINK_OPEN.search(self._pending)
            if open_tag is None:
                hold = _split_tag_prefix(self._pending, "<think>")
                emit = self._pending[:-hold] if hold else self._pending
                self._pending = self._pending[-hold:] if hold else ""
                if emit:
                    visible.append(emit)
                break
            if open_tag.start():
                visible.append(self._pending[: open_tag.start()])
            self._pending = self._pending[open_tag.end() :]
            self._skipping = True
        return "".join(visible)

    def finish(self) -> str:
        if self._skipping:
            self._pending = ""
            return ""
        leftover = self._pending
        self._pending = ""
        return leftover


def _split_tag_prefix(text: str, tag: str) -> int:
    lowered = text.lower()
    for size in range(len(tag) - 1, 0, -1):
        if lowered.endswith(tag[:size]):
            return size
    return 0


class MomaChatClient:
    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.endpoint = endpoint or os.getenv("MOMA_CHAT_COMPLETIONS_URL", "")
        self.api_key = api_key or os.getenv("MOMA_API_KEY", "")
        self.model = model or os.getenv("MOMA_MODEL", "")
        try:
            self.timeout = timeout if timeout is not None else max(1, int(os.getenv("MOMA_TIMEOUT_SECONDS", "180")))
        except ValueError:
            self.timeout = 120

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> dict[str, Any]:
        content = ""
        usage = None
        model = self.model
        saw_result = False
        for event in self.iter_chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        ):
            if event["type"] == "error":
                result = {"status": "error", "detail": event.get("detail", "")}
                if event.get("http_status"):
                    result["http_status"] = event["http_status"]
                return result
            if event["type"] == "result":
                saw_result = True
                content = event.get("content") or ""
                usage = event.get("usage")
                model = event.get("model") or model
        if not saw_result:
            return {"status": "error", "detail": "MoMA returned an empty stream"}
        return {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage,
        }

    def iter_chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        top_p: float = 0.9,
    ) -> Iterator[dict[str, Any]]:
        if not self.endpoint:
            yield {"type": "error", "detail": "MOMA_CHAT_COMPLETIONS_URL is not configured"}
            return
        if not self.model:
            yield {"type": "error", "detail": "MOMA_MODEL is not configured"}
            return
        if not self.api_key:
            yield {"type": "error", "detail": "MOMA_API_KEY is not configured"}
            return

        try:
            token_limit = max_tokens if max_tokens is not None else max(1, int(os.getenv("MOMA_MAX_TOKENS", "256")))
        except ValueError:
            token_limit = 256

        # MoMA 的 OpenAI 兼容示例使用 stream，并用 enable_thinking 控制是否先推理。
        # 巡检结论不需要推理链；关掉后首字会快很多，也不会把额度耗在思考上。
        profiles = (
            {"stream": True, "enable_thinking": False},
            {"stream": True},
            {"stream": False},
        )
        last_detail = "MoMA request failed"
        last_status = 502
        for extra in profiles:
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": token_limit,
                "temperature": temperature,
                "top_p": top_p,
                **extra,
            }
            response, failure = self._open(body)
            if failure is not None:
                last_status, last_detail = failure
                if last_status == 400:
                    continue
                yield {"type": "error", "http_status": last_status, "detail": last_detail}
                return
            assert response is not None
            try:
                yield from self._consume(response)
            finally:
                response.close()
            return
        yield {"type": "error", "http_status": last_status, "detail": last_detail}

    def _open(self, body: dict[str, Any]) -> tuple[Any, tuple[int, str] | None]:
        req = request.Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream, application/json",
            },
            method="POST",
        )
        try:
            return request.urlopen(req, timeout=self.timeout), None
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return None, (exc.code, detail)
        except error.URLError as exc:
            return None, (502, str(exc.reason))
        except TimeoutError as exc:
            return None, (504, str(exc))

    def _consume(self, response: Any) -> Iterator[dict[str, Any]]:
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            yield from self._consume_sse(response)
            return
        raw = response.read().decode("utf-8")
        if raw.lstrip().startswith("data:"):
            yield from self._consume_sse_text(raw)
            return
        yield from self._consume_json(raw)

    def _consume_json(self, raw: str) -> Iterator[dict[str, Any]]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            yield {"type": "error", "detail": str(exc)}
            return
        if not isinstance(payload, dict):
            yield {"type": "error", "detail": "MoMA returned a non-object response"}
            return
        try:
            content = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            content = ""
        visible = _VisibleText()
        text = visible.push(content) + visible.finish()
        if text:
            yield {"type": "delta", "text": text}
        yield {
            "type": "result",
            "model": payload.get("model") or self.model,
            "content": text,
            "usage": payload.get("usage"),
        }

    def _sse_event(self, block: str) -> Iterator[dict[str, Any]]:
        data = "\n".join(line[5:].strip() for line in block.split("\n") if line.startswith("data:"))
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("model"):
            self._sse_model = payload["model"]
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self._sse_usage = usage
        choices = payload.get("choices") or []
        if not choices:
            return
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        piece = delta.get("content")
        if piece is None:
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            piece = message.get("content")
        if not isinstance(piece, str) or not piece:
            return
        visible = self._visible.push(piece)
        if visible:
            self._sse_parts.append(visible)
            yield {"type": "delta", "text": visible}

    def _finish_sse(self) -> Iterator[dict[str, Any]]:
        tail = self._visible.finish()
        if tail:
            self._sse_parts.append(tail)
            yield {"type": "delta", "text": tail}
        yield {
            "type": "result",
            "model": getattr(self, "_sse_model", None) or self.model,
            "content": "".join(self._sse_parts),
            "usage": getattr(self, "_sse_usage", None),
        }

    def _consume_sse(self, response: Any) -> Iterator[dict[str, Any]]:
        self._reset_sse()
        lines: list[str] = []
        while True:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                lines.append(line)
                continue
            if lines:
                yield from self._sse_event("\n".join(lines))
                lines = []
        if lines:
            yield from self._sse_event("\n".join(lines))
        yield from self._finish_sse()

    def _consume_sse_text(self, raw: str) -> Iterator[dict[str, Any]]:
        self._reset_sse()
        block: list[str] = []
        for line in raw.splitlines():
            if line.strip():
                block.append(line.strip())
                continue
            if block:
                yield from self._sse_event("\n".join(block))
                block = []
        if block:
            yield from self._sse_event("\n".join(block))
        yield from self._finish_sse()

    def _reset_sse(self) -> None:
        self._visible = _VisibleText()
        self._sse_parts: list[str] = []
        self._sse_model: str | None = None
        self._sse_usage: dict[str, Any] | None = None
