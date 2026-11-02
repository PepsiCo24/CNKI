"""Tags and custom collection folders."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.errors import ValidationAppError
from app.database.session import get_db
from app.schemas import TagCreate, TagUpdate
from app.services.paper_service import (
    add_to_collection,
    create_collection,
    create_tag,
    delete_collection,
    delete_tag,
    list_collections,
    list_tags,
    remove_from_collection,
    update_collection,
    update_tag,
)

router = APIRouter(tags=["tags-collections"])


@router.get("/tags")
def get_tags(db: Session = Depends(get_db)):
    return ok({"items": list_tags(db)})


@router.post("/tags")
def post_tag(payload: TagCreate, db: Session = Depends(get_db)):
    return ok(create_tag(db, payload.name, payload.category, payload.color), message="标签已创建")


@router.put("/tags/{tag_id}")
def put_tag(tag_id: str, payload: TagUpdate, db: Session = Depends(get_db)):
    return ok(update_tag(db, tag_id, payload.model_dump(exclude_none=True)), message="标签已更新")


@router.delete("/tags/{tag_id}")
def remove_tag(tag_id: str, db: Session = Depends(get_db)):
    delete_tag(db, tag_id)
    return ok({"id": tag_id}, message="标签已删除")


@router.get("/collections")
def get_collections(db: Session = Depends(get_db)):
    return ok({"items": list_collections(db)})


@router.post("/collections")
def post_collection(payload: dict, db: Session = Depends(get_db)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationAppError("文件夹名称不能为空")
    return ok(
        create_collection(db, name, payload.get("parent_id"), payload.get("color", "#909399")),
        message="文件夹已创建",
    )


@router.put("/collections/{collection_id}")
def put_collection(collection_id: str, payload: dict, db: Session = Depends(get_db)):
    return ok(update_collection(db, collection_id, payload), message="文件夹已更新")


@router.delete("/collections/{collection_id}")
def remove_collection(collection_id: str, db: Session = Depends(get_db)):
    delete_collection(db, collection_id)
    return ok({"id": collection_id}, message="文件夹已删除")


@router.post("/collections/{collection_id}/papers")
def add_papers(collection_id: str, payload: dict, db: Session = Depends(get_db)):
    paper_ids = payload.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not paper_ids:
        raise ValidationAppError("请选择要加入的文献")
    added = add_to_collection(db, collection_id, [str(pid) for pid in paper_ids])
    return ok({"added": added}, message=f"已加入 {added} 篇文献")


@router.delete("/collections/{collection_id}/papers")
def remove_papers(collection_id: str, payload: dict, db: Session = Depends(get_db)):
    paper_ids = [str(pid) for pid in (payload.get("paper_ids") or [])]
    remove_from_collection(db, collection_id, paper_ids)
    return ok({"removed": len(paper_ids)}, message="已从文件夹移除")
