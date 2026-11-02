"""Source adapters.

Only permitted acquisition paths are implemented:

* official metadata export import (offline parsing)
* local fulltext takeover (folder watch / upload)
* an explicitly licensed API adapter stub which refuses to run until the user supplies
  a documented endpoint and permission reference. No private CNKI endpoints, CAPTCHA
  bypass or credential forging is implemented anywhere in this project.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.core.errors import NotConfiguredError, PermissionRequiredError
from app.models import SearchTask


class SourceAdapter(ABC):
    source_id = "base"
    label = "Base"
    capabilities: dict[str, bool] = {}

    @abstractmethod
    def retrieval_guide(self, task: SearchTask) -> dict[str, Any]: ...

    @abstractmethod
    def search(self, task: SearchTask) -> list[dict[str, Any]]: ...


class CNKIManualAdapter(SourceAdapter):
    source_id = "CNKI"
    label = "知网官方检索 + 题录导入"
    capabilities = {
        "metadata_import": True,
        "local_fulltext": True,
        "programmatic_search": False,
        "programmatic_download": False,
    }

    def retrieval_guide(self, task: SearchTask) -> dict[str, Any]:
        return {
            "source": "CNKI",
            "mode": "manual_official_search",
            "official_entry": "https://www.cnki.net",
            "fields": {
                "文献来源": task.journal or "（未限定期刊）",
                "主题": task.keywords or "（未限定主题）",
                "发表时间": {
                    "start": task.start_date.isoformat() if task.start_date else None,
                    "end": task.end_date.isoformat() if task.end_date else None,
                },
                "文献类型": {"journal": "期刊论文", "dissertation": "学位论文", "conference": "会议论文"}.get(
                    task.paper_type, task.paper_type
                ),
                "排序": {"publication_date": "发表时间", "relevance": "相关度"}.get(task.sort_by, task.sort_by),
            },
            "steps": [
                "在浏览器中打开知网官方检索页面（https://www.cnki.net）。",
                "切换到高级检索：把期刊名称填入“文献来源”，主题词填入“主题”，不要反过来。",
                "按任务条件设置发表时间起止日期与文献类型。",
                "在结果页使用知网官方“导出/参考文献”功能，选择 RIS、BibTeX 或 EndNote 格式导出。",
                "在“文献检索 → 导入题录”选择刚导出的文件并关联本任务。",
                "通过你有权使用的正规渠道下载 PDF/CAJ，放入导入目录，由系统接管归档。",
            ],
            "notices": [
                "系统不会自动登录、绕过验证码或调用未公开接口。",
                "普通知网账号的下载权限不视为批量程序化下载许可。",
                "题录与全文分开展示：只有题录时不会标记为已完成全文分析。",
            ],
        }

    def search(self, task: SearchTask) -> list[dict[str, Any]]:
        raise PermissionRequiredError(
            "手动模式不提供程序化检索：请按系统生成的检索条件在知网官方页面检索并导出题录，"
            "再通过“导入题录”完成入库。"
        )


class CNKIAuthorizedAdapter(SourceAdapter):
    source_id = "CNKI_AUTHORIZED"
    label = "知网授权数据接口（需单独许可）"
    capabilities = {
        "metadata_import": True,
        "local_fulltext": True,
        "programmatic_search": False,
        "programmatic_download": False,
    }

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def _ensure_configured(self) -> None:
        if not self.config.get("enabled"):
            raise PermissionRequiredError(
                "授权接口未启用。未经确认的批量程序化检索/下载不会启用，请先在设置中填写许可信息。"
            )
        if not self.config.get("base_url") or not self.config.get("permission_reference"):
            raise NotConfiguredError(
                "授权接口尚未配置完整：需要官方文档中的 Base URL、认证方式与许可编号。"
                "系统不会猜测知网接口地址。"
            )
        raise NotConfiguredError(
            "已记录授权配置，但当前版本未内置任何未经确认的知网 API 端点。"
            "请依据你获得的接口文档扩展 CNKIAuthorizedAdapter，并在测试环境验证后再启用。"
        )

    def retrieval_guide(self, task: SearchTask) -> dict[str, Any]:
        return {
            "source": "CNKI_AUTHORIZED",
            "mode": "licensed_api",
            "fields": {
                "journal": task.journal,
                "keywords": task.keywords,
                "start_date": task.start_date.isoformat() if task.start_date else None,
                "end_date": task.end_date.isoformat() if task.end_date else None,
            },
            "enabled": bool(self.config.get("enabled")),
            "permission_reference": self.config.get("permission_reference", ""),
            "notices": [
                "只有取得明确书面许可的接口才可使用。",
                "本适配器不会猜测或调用任何未公开端点。",
            ],
        }

    def search(self, task: SearchTask) -> list[dict[str, Any]]:
        self._ensure_configured()
        return []


def get_adapter(source: str, config: dict[str, Any] | None = None) -> SourceAdapter:
    if source == "CNKI_AUTHORIZED":
        return CNKIAuthorizedAdapter(config or {})
    return CNKIManualAdapter()
