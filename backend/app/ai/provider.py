"""Unified LLM provider adapter (OpenAI-compatible, Ollama, offline mock).

Keys never leave the backend: they are decrypted in memory for the request and are not
logged. All calls have explicit timeouts.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.settings_service import AiConfig

logger = get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    is_mock: bool = False
    raw: dict = field(default_factory=dict)


class LLMProvider:
    name = "base"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> LLMResponse:
        raise NotImplementedError

    async def test_connection(self) -> dict[str, Any]:
        response = await self.chat(
            [{"role": "user", "content": "只输出 JSON：{\"ok\": true}"}],
            temperature=0,
            max_tokens=32,
        )
        return {"ok": True, "model": response.model, "sample": response.content[:200], "is_mock": response.is_mock}


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, config: AiConfig):
        self.config = config

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.config.reasoning_effort:
            payload["reasoning_effort"] = self.config.reasoning_effort
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        timeout = httpx.Timeout(self.config.timeout, connect=min(20, self.config.timeout))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await self._post_with_json_fallback(client, headers, payload, json_mode)
        data = response.json()
        try:
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            if not content and message.get("reasoning_content"):
                content = message["reasoning_content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"模型响应格式异常：{str(data)[:300]}") from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            model=data.get("model") or self.config.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            raw={"id": data.get("id", ""), "finish_reason": data.get("choices", [{}])[0].get("finish_reason")},
        )

    async def _post_with_json_fallback(
        self, client: httpx.AsyncClient, headers: dict, payload: dict, json_mode: bool
    ) -> httpx.Response:
        try:
            response = await client.post(self._endpoint(), headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"模型请求超时（{self.config.timeout}s）") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"模型连接失败：{exc}") from exc
        if response.status_code >= 400 and json_mode:
            text = response.text
            if "response_format" in text or response.status_code in (400, 422):
                payload.pop("response_format", None)
                try:
                    response = await client.post(self._endpoint(), headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    raise LLMError(f"模型连接失败：{exc}") from exc
        if response.status_code >= 400:
            message = _safe_error_text(response)
            if response.status_code == 401:
                raise LLMError("API Key 无效或已过期（401）")
            if response.status_code == 429:
                raise LLMError("模型服务限流或余额不足（429），请稍后重试")
            raise LLMError(f"模型服务返回 {response.status_code}：{message}")
        return response


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, config: AiConfig):
        self.config = config

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> LLMResponse:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/api/chat"):
            endpoint = base
        else:
            endpoint = f"{base}/api/chat"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        timeout = httpx.Timeout(self.config.timeout, connect=min(10, self.config.timeout))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(f"Ollama 请求超时（{self.config.timeout}s）") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接 Ollama：{exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Ollama 返回 {response.status_code}：{_safe_error_text(response)}")
        data = response.json()
        return LLMResponse(
            content=(data.get("message") or {}).get("content") or "",
            model=data.get("model") or self.config.model,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            raw={"done": data.get("done")},
        )


class MockProvider(LLMProvider):
    """Deterministic offline provider. Never presented as a real model result."""

    name = "mock"

    def __init__(self, config: AiConfig):
        self.config = config

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = True,
    ) -> LLMResponse:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        analysis = _mock_analysis(user)
        return LLMResponse(
            content=json.dumps(analysis, ensure_ascii=False),
            model="deterministic-mock-v1",
            prompt_tokens=max(1, len(user) // 3),
            completion_tokens=max(1, len(json.dumps(analysis)) // 3),
            is_mock=True,
        )


def build_provider(config: AiConfig) -> LLMProvider:
    if config.provider == "mock":
        return MockProvider(config)
    if config.provider == "ollama":
        return OllamaProvider(config)
    return OpenAICompatibleProvider(config)


def _safe_error_text(response: httpx.Response) -> str:
    text = response.text or ""
    # Never echo credentials that a provider might reflect back.
    text = re.sub(r"(sk-[A-Za-z0-9_\-]{6,})", "sk-***", text)
    return text[:600]


def _mock_analysis(prompt: str) -> dict[str, Any]:
    title_match = re.search(r"标题：(.+)", prompt)
    abstract_match = re.search(r"摘要：\n(.+?)(?:\n\n【|\Z)", prompt, re.S)
    scope_match = re.search(r"【分析范围】(.+)", prompt)
    title = (title_match.group(1).strip() if title_match else "未命名文献")[:80]
    abstract = (abstract_match.group(1).strip() if abstract_match else "")[:600]
    scope = "abstract" if "仅能访问摘要" in prompt else ("fulltext_chunked" if "分块" in prompt else "fulltext")
    if scope_match and "仅基于摘要" in scope_match.group(1):
        scope = "abstract"
    problem = abstract.split("。")[0][:160] if abstract else "未明确说明"
    return {
        "one_sentence_summary": f"（模拟分析）围绕《{title}》所述问题开展研究，展示系统端到端分析流程。",
        "research_problem": problem or "未明确说明",
        "main_method": "模拟模式仅演示结构化输出，不替代真实模型对方法论的判断。",
        "claimed_innovations": [
            {
                "name": "流程验证用模拟创新点",
                "problem": problem or "未明确说明",
                "method": "由离线 Mock 提供器生成，用于验证解析、校验、审核与入库链路。",
                "difference": "固定规则生成，不代表论文真实创新。",
                "evidence": "系统模拟输出，无原文证据。",
                "page": None,
                "inferred": False,
            }
        ],
        "inferred_contributions": [],
        "innovation_summary": "模拟结果：请配置真实大模型后重新分析，以获得有依据的创新点。",
        "key_results": [],
        "research_value": "本结果仅用于验证系统流程与界面，不构成科研判断依据。",
        "limitations": [
            {"type": "claimed", "text": "模拟提供器不阅读论文内容，无法判断作者披露的局限。"},
            {"type": "inferred", "text": "结果由规则生成，不具备学术分析效力。"},
        ],
        "screening_score": 50,
        "screening_reason": "离线模拟模式固定分数，仅用于演示筛选流程，不代表论文质量。",
        "evidence": [],
        "analysis_scope": scope,
        "missing_information": ["未调用真实模型", "未验证创新点与原文的对应关系"],
        "tags_suggestion": ["模拟结果", "待真实模型复核"],
    }
