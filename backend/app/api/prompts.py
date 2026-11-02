"""Prompt template versions. Editing content creates a new version row."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.errors import NotFoundError, ValidationAppError
from app.database.session import get_db
from app.models import PromptTemplate
from app.schemas import PromptCreate, PromptUpdate
from app.services import serializers
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.get("")
def list_prompts(db: Session = Depends(get_db)):
    prompts = db.query(PromptTemplate).order_by(PromptTemplate.is_default.desc(), PromptTemplate.version.desc()).all()
    return ok({"items": [serializers.prompt_out(prompt) for prompt in prompts]})


@router.get("/{prompt_id}")
def get_prompt(prompt_id: str, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    return ok(serializers.prompt_out(prompt))


@router.post("")
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)):
    if payload.is_default:
        db.query(PromptTemplate).update({"is_default": False})
    prompt = PromptTemplate(
        name=payload.name.strip(),
        content=payload.content,
        version=1,
        is_default=payload.is_default,
        is_active=payload.is_active,
        description=payload.description,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return ok(serializers.prompt_out(prompt), message="提示词已创建")


@router.put("/{prompt_id}")
def update_prompt(prompt_id: str, payload: PromptUpdate, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    if payload.content is not None and payload.content.strip() != prompt.content.strip():
        if len(payload.content.strip()) < 20:
            raise ValidationAppError("提示词内容过短")
        # Preserve history: create a new version rather than mutating the old text.
        new_prompt = PromptTemplate(
            name=payload.name or prompt.name,
            content=payload.content,
            version=prompt.version + 1,
            is_default=bool(prompt.is_default),
            is_active=True,
            description=payload.description if payload.description is not None else prompt.description,
        )
        db.add(new_prompt)
        prompt.is_active = False
        prompt.is_default = False
        db.flush()
        SettingsService(db).set("ai.prompt_template_id", new_prompt.id, commit=False)
        db.commit()
        db.refresh(new_prompt)
        return ok(
            serializers.prompt_out(new_prompt),
            message=f"已保存为新版本 v{new_prompt.version}，历史分析结果保留原版本号",
        )
    for key in ("name", "description", "is_active"):
        value = getattr(payload, key)
        if value is not None:
            setattr(prompt, key, value)
    db.commit()
    db.refresh(prompt)
    return ok(serializers.prompt_out(prompt), message="提示词已更新")


@router.post("/{prompt_id}/activate")
def activate_prompt(prompt_id: str, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    prompt.is_active = True
    db.flush()
    SettingsService(db).set("ai.prompt_template_id", prompt.id, commit=False)
    db.commit()
    return ok(serializers.prompt_out(prompt), message="已设为当前分析提示词")


@router.post("/{prompt_id}/set-default")
def set_default(prompt_id: str, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    db.query(PromptTemplate).update({"is_default": False})
    prompt.is_default = True
    prompt.is_active = True
    db.commit()
    return ok(serializers.prompt_out(prompt), message="已设为默认提示词")


@router.post("/{prompt_id}/duplicate")
def duplicate_prompt(prompt_id: str, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    clone = PromptTemplate(
        name=f"{prompt.name}（副本）",
        content=prompt.content,
        version=1,
        is_default=False,
        is_active=True,
        description=prompt.description,
    )
    db.add(clone)
    db.commit()
    return ok(serializers.prompt_out(clone), message="提示词已复制")


@router.delete("/{prompt_id}")
def archive_prompt(prompt_id: str, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise NotFoundError("提示词不存在")
    if prompt.is_default:
        raise ValidationAppError("默认提示词不能归档")
    prompt.is_active = False
    db.commit()
    return ok(serializers.prompt_out(prompt), message="提示词已归档（历史结果不受影响）")
