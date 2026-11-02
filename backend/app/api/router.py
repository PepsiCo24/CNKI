"""Aggregate API router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import ai, dashboard, exports, imports, innovations, library, papers, prompts, review, search_tasks, settings, system, tags

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(dashboard.router)
api_router.include_router(search_tasks.router)
api_router.include_router(imports.router)
api_router.include_router(papers.router)
api_router.include_router(ai.router)
api_router.include_router(review.router)
api_router.include_router(library.router)
api_router.include_router(innovations.router)
api_router.include_router(tags.router)
api_router.include_router(prompts.router)
api_router.include_router(settings.router)
api_router.include_router(exports.router)
