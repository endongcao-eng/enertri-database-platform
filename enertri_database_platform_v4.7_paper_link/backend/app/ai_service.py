from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx


class AIUnavailableError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


@dataclass(slots=True)
class AIFile:
    filename: str
    content: bytes
    content_type: str | None = None
    detail: str = "high"

    @property
    def mime_type(self) -> str:
        return self.content_type or mimetypes.guess_type(self.filename)[0] or "application/octet-stream"


class AIService:
    """Minimal Responses API client.

    The server keeps the API key in backend environment variables. Files are sent
    directly to the model for the current request and are not uploaded to a
    persistent remote file store.
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.1").strip() or "gpt-5.1"
        self.timeout = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "180"))

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.available,
            "provider": "openai_responses" if self.available else "disabled",
            "model": self.model if self.available else None,
            "base_url": self.base_url if self.available else None,
        }

    @staticmethod
    def _data_uri(file: AIFile) -> str:
        encoded = base64.b64encode(file.content).decode("ascii")
        return f"data:{file.mime_type};base64,{encoded}"

    def _content_items(self, prompt: str, files: Iterable[AIFile] | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for file in files or []:
            mime = file.mime_type
            if mime.startswith("image/"):
                items.append({"type": "input_image", "image_url": self._data_uri(file), "detail": file.detail})
            else:
                item: dict[str, Any] = {
                    "type": "input_file",
                    "filename": Path(file.filename).name,
                    "file_data": self._data_uri(file),
                }
                items.append(item)
        return items

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            for content in item.get("content", []) or []:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        output = "\n".join(chunks).strip()
        if not output:
            raise AIResponseError("AI 服务未返回可解析的文本结果")
        return output

    def _unmetered_generate_text(
        self,
        prompt: str,
        *,
        files: Iterable[AIFile] | None = None,
        instructions: str | None = None,
        reasoning_effort: str = "medium",
    ) -> str:
        if not self.available:
            raise AIUnavailableError("未配置 OPENAI_API_KEY，当前仅可使用文献检索和规则型焊接分析功能")
        body: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": "user", "content": self._content_items(prompt, files)}],
            # Avoid creating reusable response state for unpublished papers or production data.
            "store": False,
            "max_output_tokens": int(os.getenv("AI_MAX_OUTPUT_TOKENS", "1024")),
        }
        if instructions:
            body["instructions"] = instructions
        if reasoning_effort in {"low", "medium", "high"}:
            body["reasoning"] = {"effort": reasoning_effort}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/responses", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise AIResponseError(f"无法连接 AI 服务：{exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:1000]
            try:
                error = response.json().get("error", {})
                detail = error.get("message") or detail
            except Exception:
                pass
            raise AIResponseError(f"AI 服务请求失败（{response.status_code}）：{detail}")
        payload = response.json()
        return self._extract_output_text(payload), payload.get("usage", {})

    def generate_text(self, prompt: str, *, user_id: int | None = None, files=None, instructions=None, reasoning_effort="medium") -> str:
        if not self.available:
            raise AIUnavailableError("未配置外部 AI 服务")
        if os.getenv("AI_BUDGET_ENABLED", "false").lower() != "true":
            raise AIUnavailableError("外部 AI 费用保护尚未启用，请联系管理员")
        # File/image tokenization and provider-specific billing have no safe generic
        # bound. Keep these paid routes disabled until separately budgeted.
        files=list(files or [])
        if files:
            raise AIUnavailableError("文件/图像外部 AI 暂未开放；可使用本地解析与OCR")
        if len((prompt+(instructions or "")).encode()) > int(os.getenv("AI_MAX_INPUT_BYTES", "16000")):
            raise AIUnavailableError("AI 输入超出试用长度额度")
        if self.model != os.getenv("AI_BUDGET_MODEL", ""):
            raise AIUnavailableError("模型未纳入费用核算配置")
        from decimal import Decimal
        from .controls import reserve_ai, finish_ai, usd_micros
        input_rate=Decimal(os.getenv("AI_INPUT_USD_PER_MILLION", "0"))
        output_rate=Decimal(os.getenv("AI_OUTPUT_USD_PER_MILLION", "0"))
        if not input_rate.is_finite() or not output_rate.is_finite() or input_rate<=0 or output_rate<=0:
            raise AIUnavailableError("请先核对模型计价并配置正数费率")
        # UTF-8 byte count + protocol allowance is conservative for text-only BPE.
        bound=(Decimal(len((prompt+(instructions or "")).encode())+2048)*input_rate + Decimal(int(os.getenv("AI_MAX_OUTPUT_TOKENS","1024")))*output_rate)
        if bound > usd_micros("AI_REQUEST_RESERVATION_USD", "0.10"):
            raise AIUnavailableError("本次请求最大估算费用超过单次预算")
        rid=reserve_ai(user_id)
        try:
            output, usage=self._unmetered_generate_text(prompt, files=files, instructions=instructions, reasoning_effort=reasoning_effort)
            finish_ai(rid,{"provider_usage":usage,"model":self.model,"input_usd_per_million":str(input_rate),"output_usd_per_million":str(output_rate)})
            return output
        except BaseException:
            finish_ai(rid,failed=True)
            raise

    def generate_json(self, prompt: str, *, user_id: int | None = None, instructions: str | None = None) -> dict[str, Any]:
        text = self.generate_text(prompt, user_id=user_id, instructions=instructions, reasoning_effort="medium")
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise AIResponseError("AI 返回内容不是有效 JSON，请重试")


ai_service = AIService()
