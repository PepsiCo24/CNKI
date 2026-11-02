"""Structured AI analysis pipeline: scope selection, chunking, repair, persistence."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.prompts import (
    ABSTRACT_ONLY_NOTE,
    CHUNKED_NOTE,
    CHUNK_EXTRACTION_PROMPT,
    FULLTEXT_NOTE,
    RETRY_REPAIR_PROMPT,
    SCHEMA_INSTRUCTION,
    USER_PROMPT_TEMPLATE,
)
from app.ai.provider import LLMError, LLMResponse, build_provider
from app.core.config import get_settings
from app.core.constants import AiStatus, AnalysisScope, ReviewStatus
from app.core.logging import get_logger
from app.core.utils import sha256_text, utcnow
from app.database.fts import index_paper
from app.models import AiAnalysisJob, AiAnalysisResult, InnovationItem, Paper, PaperText, PromptTemplate
from app.parsers.pdf_parser import render_with_page_markers
from app.schemas import AnalysisOutput
from app.services.log_service import log_event
from app.services.settings_service import AiConfig, SettingsService

logger = get_logger(__name__)

MAX_REPAIR_ATTEMPTS = 2
MAX_CHUNKS = 20
ProgressCallback = Callable[[int, str], Awaitable[None]] | None


class AnalysisError(RuntimeError):
    pass


def extract_json(text: str) -> dict[str, Any]:
    if not text or not text.strip():
        raise AnalysisError("模型返回为空")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(cleaned[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise AnalysisError("模型输出不是合法 JSON")


def _validation_text(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:12]:
        location = ".".join(str(item) for item in error.get("loc", []))
        parts.append(f"{location}: {error.get('msg')}")
    return "; ".join(parts)[:3000]


class Analyzer:
    def __init__(self, db: Session, progress: ProgressCallback = None):
        self.db = db
        self.progress = progress
        self.settings = SettingsService(db)
        self.config = self.settings.ai_config()
        self.provider = build_provider(self.config)
        self.tokens_prompt = 0
        self.tokens_completion = 0
        self.calls: list[LLMResponse] = []

    async def _notify(self, percent: int, message: str) -> None:
        if self.progress:
            try:
                await self.progress(percent, message)
            except Exception:  # pragma: no cover - progress must never break analysis
                logger.debug("progress callback failed", exc_info=True)

    async def run(
        self,
        paper_id: str,
        *,
        ai_job_id: str | None = None,
        force: bool = False,
        prompt_template_id: str | None = None,
    ) -> AiAnalysisResult:
        paper = self.db.get(Paper, paper_id)
        if not paper:
            raise AnalysisError("文献不存在")
        job = self.db.get(AiAnalysisJob, ai_job_id) if ai_job_id else None
        prompt = self._resolve_prompt(prompt_template_id)
        text_row = self.db.query(PaperText).filter(PaperText.paper_id == paper_id).first()

        if job:
            job.status = AiStatus.RUNNING
            job.provider = self.config.provider
            job.model = self.config.model
            job.prompt_template_id = prompt.id
            job.prompt_version = prompt.version
            job.started_at = utcnow()
            self.db.commit()
        paper.ai_status = AiStatus.RUNNING
        if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
            paper.review_status = ReviewStatus.ANALYZING
        self.db.commit()

        try:
            content, scope, chunk_count, truncated = await self._prepare_content(paper, text_row)
            cache_key = self._cache_key(content, prompt, scope)
            if job:
                job.cache_key = cache_key
                job.input_chars = len(content)
                job.chunk_count = chunk_count
                job.analysis_scope = scope
                self.db.commit()

            if not force:
                cached = (
                    self.db.query(AiAnalysisResult)
                    .filter(
                        AiAnalysisResult.paper_id == paper.id,
                        AiAnalysisResult.cache_key == cache_key,
                        AiAnalysisResult.is_current.is_(True),
                    )
                    .order_by(AiAnalysisResult.created_at.desc())
                    .first()
                )
                if cached:
                    await self._notify(100, "命中缓存，复用相同文件/提示词/模型参数的既有结果")
                    paper.ai_status = AiStatus.CACHED
                    if paper.review_status not in (
                        ReviewStatus.INCLUDED,
                        ReviewStatus.EXCLUDED,
                        ReviewStatus.DEFERRED,
                    ):
                        paper.review_status = ReviewStatus.PENDING_REVIEW
                    if job:
                        job.status = AiStatus.COMPLETED
                        job.result_id = cached.id
                        job.finished_at = utcnow()
                        job.tokens_prompt = 0
                        job.tokens_completion = 0
                    self.db.commit()
                    log_event(
                        self.db,
                        "AI 分析命中缓存，未重复调用模型",
                        job_id=job.background_job_id if job else None,
                        detail={"paper_id": paper.id, "result_id": cached.id},
                        commit=True,
                    )
                    return cached

            await self._notify(25, "正在构建分析输入")
            user_prompt = self._build_user_prompt(paper, content, scope, truncated)
            messages = [
                {"role": "system", "content": prompt.content.strip() + "\n\n" + SCHEMA_INSTRUCTION},
                {"role": "user", "content": user_prompt},
            ]
            await self._notify(45, "正在调用大模型")
            output, raw = await self._ask_with_repair(messages, source_for_repair=user_prompt)
            output.analysis_scope = self._enforce_scope(output.analysis_scope, scope)
            if truncated and not any("超出" in item for item in output.missing_information):
                output.missing_information.append("原文超出单次输入上限，后文未纳入本次分析")
            if scope == AnalysisScope.ABSTRACT and not any("摘要" in item for item in output.missing_information):
                output.missing_information.append("仅基于摘要分析，未读取全文")

            await self._notify(80, "正在保存结构化结果")
            result = self._save_result(
                paper,
                output,
                raw,
                prompt,
                scope,
                content,
                cache_key,
                chunk_count,
                job,
            )
            if job:
                job.status = AiStatus.COMPLETED
                job.result_id = result.id
                job.finished_at = utcnow()
                job.tokens_prompt = self.tokens_prompt
                job.tokens_completion = self.tokens_completion
                job.estimated_cost = self._estimate_cost()
                self.db.commit()
            await self._notify(100, "分析完成，已进入待人工审核")
            log_event(
                self.db,
                f"AI 分析完成：{paper.title[:60]}",
                job_id=job.background_job_id if job else None,
                detail={"paper_id": paper.id, "scope": scope, "is_mock": result.is_mock},
                commit=True,
            )
            return result
        except Exception as exc:
            message = self._friendly_error(exc)
            paper.ai_status = AiStatus.FAILED
            if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
                paper.review_status = ReviewStatus.ANALYSIS_FAILED
            if job:
                job.status = AiStatus.FAILED
                job.error = message[:4000]
                job.finished_at = utcnow()
                job.tokens_prompt = self.tokens_prompt
                job.tokens_completion = self.tokens_completion
                job.attempts = (job.attempts or 0) + 1
            self.db.commit()
            log_event(
                self.db,
                f"AI 分析失败：{message[:300]}",
                level="error",
                job_id=job.background_job_id if job else None,
                detail={"paper_id": paper.id},
                commit=True,
            )
            raise AnalysisError(message) from exc

    # ------------------------------------------------------------------ preparation
    def _resolve_prompt(self, prompt_template_id: str | None) -> PromptTemplate:
        if prompt_template_id:
            prompt = self.db.get(PromptTemplate, prompt_template_id)
            if prompt:
                return prompt
        configured = self.settings.get("ai.prompt_template_id", "")
        if configured:
            prompt = self.db.get(PromptTemplate, configured)
            if prompt:
                return prompt
        prompt = (
            self.db.query(PromptTemplate)
            .filter(PromptTemplate.is_default.is_(True))
            .order_by(PromptTemplate.version.desc())
            .first()
        )
        if not prompt:
            prompt = (
                self.db.query(PromptTemplate)
                .filter(PromptTemplate.is_active.is_(True))
                .order_by(PromptTemplate.version.desc())
                .first()
            )
        if not prompt:
            raise AnalysisError("未找到可用的提示词模板")
        return prompt

    async def _prepare_content(
        self, paper: Paper, text_row: PaperText | None
    ) -> tuple[str, str, int, bool]:
        max_chars = max(2000, self.config.max_input_chars)
        has_fulltext = bool(text_row and text_row.content and len(text_row.content.strip()) >= 100)
        if has_fulltext:
            pages = text_row.page_map or []
            full_length = len(text_row.content)
            if full_length <= max_chars:
                content = render_with_page_markers(text_row.content, pages, max_chars)
                if not content:
                    content = text_row.content[:max_chars]
                return content, AnalysisScope.FULLTEXT, 0, False
            await self._notify(15, "论文较长，正在分块提取")
            chunk_notes, chunk_count = await self._chunk_extract(paper, pages, max_chars)
            header = (
                "【分块提取要点（系统生成，供汇总参考）】\n"
                + json.dumps(chunk_notes, ensure_ascii=False, indent=2)[: max_chars // 2]
            )
            abstract_part = f"\n\n【摘要】\n{paper.abstract[:3000]}" if paper.abstract else ""
            return header + abstract_part, AnalysisScope.FULLTEXT_CHUNKED, chunk_count, True
        if paper.abstract.strip():
            content = f"【摘要】\n{paper.abstract.strip()}"
            return content, AnalysisScope.ABSTRACT, 0, False
        content = (
            f"【题录信息】\n标题：{paper.title}\n作者：{paper.authors_text}\n期刊：{paper.journal}\n"
            f"发表时间：{paper.publication_date_raw or paper.year or '未明确说明'}"
        )
        return content, AnalysisScope.METADATA, 0, False

    async def _chunk_extract(
        self, paper: Paper, pages: list[dict], max_chars: int
    ) -> tuple[list[dict], int]:
        chunk_limit = max(6000, int(max_chars * 0.6))
        chunks: list[dict] = []
        current: list[dict] = []
        current_len = 0
        for page in pages:
            text = page.get("text") or ""
            length = len(text)
            if current and current_len + length > chunk_limit:
                chunks.append({"pages": current, "length": current_len})
                current, current_len = [], 0
            current.append(page)
            current_len += length
            if current_len >= chunk_limit:
                chunks.append({"pages": current, "length": current_len})
                current, current_len = [], 0
        if current:
            chunks.append({"pages": current, "length": current_len})
        chunks = chunks[:MAX_CHUNKS]
        notes: list[dict] = []
        for index, chunk in enumerate(chunks, start=1):
            await self._notify(
                15 + int(20 * index / max(1, len(chunks))),
                f"分块提取 {index}/{len(chunks)}",
            )
            segment = render_with_page_markers("", chunk["pages"], chunk_limit)
            start_page = chunk["pages"][0].get("page", 1)
            end_page = chunk["pages"][-1].get("page", 1)
            prompt = CHUNK_EXTRACTION_PROMPT.format(start_page=start_page, end_page=end_page)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"标题：{paper.title}\n\n{segment}"},
            ]
            try:
                data, _response = await self._ask_once(messages, max_tokens=1800)
                data["pages"] = f"{start_page}-{end_page}"
                notes.append(data)
            except (AnalysisError, LLMError) as exc:
                logger.warning("chunk %s extraction failed: %s", index, exc)
                notes.append(
                    {
                        "pages": f"{start_page}-{end_page}",
                        "summary": "该分块未能结构化提取",
                        "error": str(exc)[:300],
                    }
                )
        return notes, len(chunks)

    def _build_user_prompt(
        self, paper: Paper, content: str, scope: str, truncated: bool
    ) -> str:
        if scope == AnalysisScope.ABSTRACT:
            scope_label, scope_note = "仅摘要（abstract）", ABSTRACT_ONLY_NOTE
        elif scope == AnalysisScope.METADATA:
            scope_label, scope_note = "仅题录（metadata）", ABSTRACT_ONLY_NOTE
        elif scope == AnalysisScope.FULLTEXT_CHUNKED:
            scope_label, scope_note = "全文分块汇总（fulltext_chunked）", CHUNKED_NOTE
        else:
            scope_label, scope_note = "全文（fulltext）", FULLTEXT_NOTE
        date_text = paper.publication_date_raw or (str(paper.year) if paper.year else "未明确说明")
        return USER_PROMPT_TEMPLATE.format(
            title=paper.title,
            authors=paper.authors_text or "未明确说明",
            journal=paper.journal or "未明确说明",
            publication_date=date_text,
            doi=paper.doi or "未明确说明",
            keywords="; ".join(paper.keywords or []) or "未明确说明",
            abstract=paper.abstract.strip() or "未提供摘要",
            scope_label=scope_label,
            scope_note=scope_note,
            content=content,
        )

    # ---------------------------------------------------------------------- model
    async def _ask_once(self, messages: list[dict], *, max_tokens: int | None = None) -> tuple[dict, LLMResponse]:
        response = await self.provider.chat(
            messages,
            temperature=self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            json_mode=True,
        )
        self.calls.append(response)
        self.tokens_prompt += response.prompt_tokens
        self.tokens_completion += response.completion_tokens
        return extract_json(response.content), response

    async def _ask_with_repair(
        self, messages: list[dict], *, source_for_repair: str
    ) -> tuple[AnalysisOutput, str]:
        last_error = ""
        for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            if attempt > 0:
                await self._notify(45, f"输出校验未通过，正在进行第 {attempt} 次修复")
            try:
                data, response = await self._ask_once(messages)
                output = AnalysisOutput.model_validate(data)
                return output, response.content
            except (AnalysisError, ValidationError) as exc:
                last_error = _validation_text(exc) if isinstance(exc, ValidationError) else str(exc)
                logger.warning("AI output validation failed (attempt %s): %s", attempt + 1, last_error)
                if attempt >= MAX_REPAIR_ATTEMPTS:
                    break
                schema = json.dumps(AnalysisOutput.model_json_schema(), ensure_ascii=False)[:6000]
                messages = [
                    {
                        "role": "system",
                        "content": "你是 JSON 修复器。只输出通过 schema 校验的 JSON 对象，不要解释。",
                    },
                    {
                        "role": "user",
                        "content": RETRY_REPAIR_PROMPT.format(
                            errors=last_error,
                            schema=schema,
                            source=source_for_repair[:12000],
                        ),
                    },
                ]
        raise AnalysisError(f"模型输出连续 {MAX_REPAIR_ATTEMPTS + 1} 次未通过结构化校验：{last_error[:500]}")

    # -------------------------------------------------------------------- persistence
    def _cache_key(self, content: str, prompt: PromptTemplate, scope: str) -> str:
        material = "|".join(
            [
                sha256_text(content),
                prompt.id,
                str(prompt.version),
                self.config.provider,
                self.config.model,
                str(self.config.temperature),
                str(self.config.max_tokens),
                scope,
            ]
        )
        return sha256_text(material)

    def _estimate_cost(self) -> float:
        return round(
            (self.tokens_prompt / 1000) * self.config.cost_input_per_1k
            + (self.tokens_completion / 1000) * self.config.cost_output_per_1k,
            6,
        )

    def _save_result(
        self,
        paper: Paper,
        output: AnalysisOutput,
        raw: str,
        prompt: PromptTemplate,
        scope: str,
        content: str,
        cache_key: str,
        chunk_count: int,
        job: AiAnalysisJob | None,
    ) -> AiAnalysisResult:
        self.db.query(AiAnalysisResult).filter(
            AiAnalysisResult.paper_id == paper.id, AiAnalysisResult.is_current.is_(True)
        ).update({"is_current": False})
        result = AiAnalysisResult(
            paper_id=paper.id,
            job_id=job.id if job else None,
            prompt_template_id=prompt.id,
            prompt_version=prompt.version,
            provider=self.config.provider,
            model=self.config.model,
            parameters={
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "reasoning_effort": self.config.reasoning_effort,
                "chunk_count": chunk_count,
            },
            analysis_scope=scope,
            input_chars=len(content),
            is_mock=self.config.provider == "mock" or any(r.is_mock for r in self.calls),
            one_sentence_summary=output.one_sentence_summary,
            research_problem=output.research_problem,
            main_method=output.main_method,
            claimed_innovations=[item.model_dump() for item in output.claimed_innovations],
            inferred_contributions=[item.model_dump() for item in output.inferred_contributions],
            innovation_summary=output.innovation_summary,
            key_results=[item.model_dump() for item in output.key_results],
            research_value=output.research_value,
            limitations=[item.model_dump() for item in output.limitations],
            screening_score=output.screening_score,
            screening_reason=output.screening_reason,
            evidence=[item.model_dump() for item in output.evidence],
            missing_information=output.missing_information,
            tags_suggestion=output.tags_suggestion,
            raw_response=raw[:200000],
            is_current=True,
            cache_key=cache_key,
        )
        self.db.add(result)
        self.db.flush()
        self._create_innovation_items(paper, result, output)
        paper.ai_status = AiStatus.COMPLETED
        if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
            paper.review_status = ReviewStatus.PENDING_REVIEW
        paper.updated_at = utcnow()
        index_paper(self.db, paper)
        self.db.commit()
        self._write_artifact(paper, result)
        return result

    def _create_innovation_items(self, paper: Paper, result: AiAnalysisResult, output: AnalysisOutput) -> None:
        items = []
        for item in output.claimed_innovations:
            items.append((item, False))
        if not items:
            for item in output.inferred_contributions:
                items.append((item, True))
        for seq, (item, inferred) in enumerate(items[:3], start=1):
            name = item.name or f"创新点 {seq}"
            self.db.add(
                InnovationItem(
                    paper_id=paper.id,
                    result_id=result.id,
                    seq=seq,
                    name=name[:300],
                    core_technique=(item.method or "")[:500],
                    description=(item.difference or item.problem or item.method or "")[:4000],
                    evidence=(item.evidence or "")[:4000],
                    page=item.page,
                    tags_snapshot=output.tags_suggestion[:8],
                )
            )

    def _write_artifact(self, paper: Paper, result: AiAnalysisResult) -> None:
        settings = get_settings()
        payload = {
            "paper_id": paper.id,
            "title": paper.title,
            "result_id": result.id,
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "analysis_scope": result.analysis_scope,
            "is_mock": result.is_mock,
            "analysis": {
                "one_sentence_summary": result.one_sentence_summary,
                "research_problem": result.research_problem,
                "main_method": result.main_method,
                "claimed_innovations": result.claimed_innovations,
                "inferred_contributions": result.inferred_contributions,
                "innovation_summary": result.innovation_summary,
                "key_results": result.key_results,
                "research_value": result.research_value,
                "limitations": result.limitations,
                "screening_score": result.screening_score,
                "screening_reason": result.screening_reason,
                "evidence": result.evidence,
                "missing_information": result.missing_information,
            },
            "created_at": result.created_at.isoformat() if result.created_at else datetime.now(timezone.utc).isoformat(),
        }
        target = settings.ai_results_dir / f"{paper.id}.json"
        try:
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            logger.warning("Could not write AI artifact: %s", exc)

    @staticmethod
    def _enforce_scope(model_scope: str, actual_scope: str) -> str:
        if actual_scope == AnalysisScope.ABSTRACT:
            return AnalysisScope.ABSTRACT
        if actual_scope == AnalysisScope.METADATA:
            return AnalysisScope.METADATA
        if actual_scope == AnalysisScope.FULLTEXT_CHUNKED:
            return AnalysisScope.FULLTEXT_CHUNKED
        if model_scope == AnalysisScope.ABSTRACT:
            return AnalysisScope.ABSTRACT
        return AnalysisScope.FULLTEXT

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, AnalysisError):
            return str(exc)
        if isinstance(exc, LLMError):
            return str(exc)
        if isinstance(exc, ValidationError):
            return f"分析结果校验失败：{_validation_text(exc)}"
        return f"分析失败：{exc}"


def artifact_path(paper_id: str) -> Path:
    return get_settings().ai_results_dir / f"{paper_id}.json"
