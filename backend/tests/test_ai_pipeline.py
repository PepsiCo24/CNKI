"""AI pipeline tests with the deterministic mock provider and repair loop."""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.ai.analyzer import AnalysisError, Analyzer, extract_json
from app.ai.provider import LLMResponse, MockProvider
from app.core.constants import AnalysisScope
from app.models import AiAnalysisJob, AiAnalysisResult, InnovationItem, Paper, PaperText
from app.services.settings_service import SettingsService


def _paper_with_text(
    db,
    text: str | None = (
        "1 引言\n边坡稳定性预测是岩土工程的重要问题。传统方法依赖经验参数，计算成本较高。"
        "本文针对该问题提出一种改进随机森林方法。\n"
        "2 研究方法\n采用递归特征消除筛选参数，并使用贝叶斯优化调整超参数。\n"
        "3 实验与结果\n在示例数据集上开展五折交叉验证，改进模型的平均绝对误差为 0.021。\n"
        "4 结论\n该方法在示例数据上降低了预测误差，但仍需真实工程验证。"
    ),
) -> Paper:
    paper = Paper(
        title="边坡稳定性预测方法研究",
        title_normalized="边坡稳定性预测方法研究",
        authors=["张三"],
        authors_text="张三",
        journal="岩土力学",
        year=2024,
        abstract="针对边坡稳定性问题，提出改进随机森林方法，并在示例数据上验证。",
        keywords=["边坡", "随机森林"],
    )
    db.add(paper)
    db.flush()
    if text:
        db.add(
            PaperText(
                paper_id=paper.id,
                content=text,
                page_map=[{"page": 1, "text": text, "char_start": 0, "char_end": len(text)}],
                char_count=len(text),
                page_count=1,
                quality="text",
            )
        )
    db.commit()
    return paper


def test_mock_analysis_is_structured_and_labeled(db):
    paper = _paper_with_text(db)
    SettingsService(db).set("ai.provider", "mock")
    job = AiAnalysisJob(paper_id=paper.id, status="queued", provider="mock", model="deterministic-mock-v1")
    db.add(job)
    db.commit()
    analyzer = Analyzer(db)
    result = asyncio.run(analyzer.run(paper.id, ai_job_id=job.id))
    assert result.is_mock is True
    assert result.analysis_scope == AnalysisScope.FULLTEXT
    assert 0 <= result.screening_score <= 100
    assert result.one_sentence_summary
    assert len(result.claimed_innovations) <= 3
    db.refresh(paper)
    assert paper.ai_status == "completed"
    assert paper.review_status == "pending_review"
    assert db.query(InnovationItem).filter(InnovationItem.paper_id == paper.id).count() >= 1
    db.refresh(job)
    assert job.status == "completed"
    assert job.result_id == result.id


def test_cache_reuses_same_result_without_second_model_call(db):
    paper = _paper_with_text(db)
    SettingsService(db).set("ai.provider", "mock")
    analyzer = Analyzer(db)
    first = asyncio.run(analyzer.run(paper.id))
    second = asyncio.run(Analyzer(db).run(paper.id))
    assert first.id == second.id
    assert db.query(AiAnalysisResult).filter(AiAnalysisResult.paper_id == paper.id).count() == 1
    db.refresh(paper)
    assert paper.ai_status == "cached"


def test_force_creates_new_version_and_keeps_old(db):
    paper = _paper_with_text(db)
    SettingsService(db).set("ai.provider", "mock")
    first = asyncio.run(Analyzer(db).run(paper.id))
    second = asyncio.run(Analyzer(db).run(paper.id, force=True))
    assert first.id != second.id
    db.refresh(first)
    assert first.is_current is False
    assert second.is_current is True
    assert db.query(AiAnalysisResult).filter(AiAnalysisResult.paper_id == paper.id).count() == 2


def test_abstract_only_scope_is_enforced(db):
    paper = _paper_with_text(db, text=None)
    SettingsService(db).set("ai.provider", "mock")
    result = asyncio.run(Analyzer(db).run(paper.id))
    assert result.analysis_scope == AnalysisScope.ABSTRACT
    assert any("摘要" in item for item in result.missing_information)


class _FakeProvider:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    async def chat(self, messages, *, temperature=0.2, max_tokens=4096, json_mode=True):
        self.calls += 1
        content = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        return LLMResponse(content=content, model="fake", prompt_tokens=10, completion_tokens=10)


def _valid_payload() -> dict:
    return {
        "one_sentence_summary": "提出改进随机森林方法并验证其有效性。",
        "research_problem": "边坡稳定性预测精度不足",
        "main_method": "改进随机森林",
        "claimed_innovations": [
            {
                "name": "特征选择改进",
                "problem": "特征冗余",
                "method": "递归特征消除",
                "difference": "降低维度",
                "evidence": "原文第2节",
                "page": 1,
                "inferred": False,
            }
        ],
        "inferred_contributions": [],
        "innovation_summary": "方法组合有参考价值",
        "key_results": [],
        "research_value": "可用于方法复现",
        "limitations": [{"type": "claimed", "text": "样本有限"}],
        "screening_score": 70,
        "screening_reason": "方法有一定新意",
        "evidence": [{"section": "方法", "page": 1, "quote": "原文短引文", "supports": "支持创新点"}],
        "analysis_scope": "fulltext",
        "missing_information": [],
        "tags_suggestion": ["边坡工程"],
    }


def test_json_repair_loop_recovers_from_invalid_output(db):
    paper = _paper_with_text(db)
    SettingsService(db).set("ai.provider", "mock")
    analyzer = Analyzer(db)
    analyzer.provider = _FakeProvider(["这不是 JSON", json.dumps(_valid_payload(), ensure_ascii=False)])
    output, raw = asyncio.run(
        analyzer._ask_with_repair(
            [{"role": "user", "content": "分析这篇论文"}], source_for_repair="论文文本"
        )
    )
    assert analyzer.provider.calls == 2
    assert output.screening_score == 70
    assert raw


def test_json_repair_is_bounded(db):
    paper = _paper_with_text(db)
    SettingsService(db).set("ai.provider", "mock")
    analyzer = Analyzer(db)
    analyzer.provider = _FakeProvider(["bad", "still bad", "nope", "never"])
    with pytest.raises(AnalysisError):
        asyncio.run(
            analyzer._ask_with_repair(
                [{"role": "user", "content": "分析"}], source_for_repair="论文"
            )
        )
    assert analyzer.provider.calls == 3  # initial + 2 repairs, never infinite


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('结果如下：{"a": 2} 请查收') == {"a": 2}
    with pytest.raises(AnalysisError):
        extract_json("no json here")


def test_schema_rejects_out_of_range_score(db):
    from app.schemas import AnalysisOutput

    payload = _valid_payload()
    payload["screening_score"] = 150
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(payload)
