"""Database bootstrap, default prompt seeding and idempotent startup."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.prompts import DEFAULT_PROMPT_VERSION, DEFAULT_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import get_secret_store
from app.database.fts import ensure_fts, rebuild_all
from app.database.session import Base, SessionLocal, engine
from app.models import PromptTemplate, Tag

logger = get_logger(__name__)

DEFAULT_TAGS = [
    ("岩土工程", "研究方向", "#409EFF"),
    ("数值模拟", "研究方法", "#67C23A"),
    ("机器学习", "研究方法", "#67C23A"),
    ("室内试验", "实验类型", "#E6A23C"),
    ("现场监测", "实验类型", "#E6A23C"),
    ("重要", "阅读优先级", "#F56C6C"),
    ("待精读", "阅读优先级", "#909399"),
]

DEFAULT_SETTINGS: dict[str, object] = {
    "ai.provider": "mock",
    "ai.base_url": "https://api.deepseek.com/v1",
    "ai.model": "deepseek-chat",
    "ai.temperature": 0.2,
    "ai.max_tokens": 4096,
    "ai.timeout": 120,
    "ai.max_input_chars": 60000,
    "ai.concurrency": 1,
    "ai.reasoning_effort": "",
    "ai.cost_input_per_1k": 0.0,
    "ai.cost_output_per_1k": 0.0,
    "ai.auto_analyze": True,
    "ai.auto_after_analysis_review": True,
    "data.import_dir": "",
    "data.watch_enabled": False,
    "data.naming_pattern": "{year}_{title}_{first_author}",
    "data.auto_backup": False,
    "review.default_sort": "score_desc",
    "review.shortcuts": {"include": "Ctrl+Enter", "exclude": "Ctrl+Backspace", "defer": "Ctrl+D"},
    "cnki.account_username": "",
    "cnki.account_institution": "",
    "cnki.account_note": "",
    "cnki.auto_import_downloads": True,
    "cnki.authorized_enabled": False,
    "cnki.authorized_base_url": "",
    "cnki.authorized_permission_reference": "",
    "cnki.authorized_daily_limit": 200,
    "app.theme": "light",
}


def init_db() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    get_secret_store()
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        ensure_fts(db)
        _seed_prompt(db)
        _seed_tags(db)
        _seed_settings(db)
        db.commit()
        _backfill_index(db)
    finally:
        db.close()
    logger.info("Database ready at %s", settings.db_path)


def _seed_prompt(db: Session) -> None:
    existing = db.query(PromptTemplate).filter(PromptTemplate.is_default.is_(True)).first()
    if existing:
        return
    prompt = PromptTemplate(
        name="默认科研论文分析提示词",
        content=DEFAULT_SYSTEM_PROMPT,
        version=DEFAULT_PROMPT_VERSION,
        is_default=True,
        is_active=True,
        description="内置默认系统提示词，可在设置中心修改；修改不会覆盖历史分析结果。",
    )
    db.add(prompt)


def _seed_tags(db: Session) -> None:
    existing = {name for (name,) in db.query(Tag.name).all()}
    for name, category, color in DEFAULT_TAGS:
        if name not in existing:
            db.add(Tag(name=name, category=category, color=color))


def _seed_settings(db: Session) -> None:
    # Defaults are applied at read-time; only persist the import dir for discoverability.
    from app.services.settings_service import SettingsService

    service = SettingsService(db)
    if not service.get("data.import_dir"):
        service.set("data.import_dir", str(get_settings().imports_dir), commit=False)


def _backfill_index(db: Session) -> None:
    try:
        indexed = db.execute(
            __import__("sqlalchemy").text("SELECT COUNT(*) FROM paper_fts")
        ).scalar()
        from app.models import Paper

        total = db.query(Paper).filter(Paper.is_deleted.is_(False)).count()
        if total and indexed != total:
            rebuild_all(db)
    except Exception as exc:  # pragma: no cover
        logger.warning("FTS backfill skipped: %s", exc)
