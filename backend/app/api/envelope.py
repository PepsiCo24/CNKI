"""Consistent API envelope and exception handlers."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


def ok(data: Any = None, message: str | None = None) -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def page_data(items: list[Any], total: int, page: int, page_size: int, **extra: Any) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page, "page_size": page_size, **extra}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {"code": exc.code, "message": exc.message, "detail": exc.detail},
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        messages = []
        safe_errors = []
        for error in exc.errors()[:20]:
            location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
            message = str(error.get("msg") or "校验失败")
            messages.append(f"{location}: {message}")
            safe_errors.append(
                {"loc": [str(part) for part in error.get("loc", [])], "msg": message, "type": str(error.get("type", ""))}
            )
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "validation_error",
                    "message": "输入校验失败：" + ("；".join(messages[:5]) or "请检查输入"),
                    "detail": {"errors": safe_errors},
                },
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {"code": "http_error", "message": str(exc.detail), "detail": {}},
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "internal_error",
                    "message": "服务器内部错误，请查看 data/logs/app.log",
                    "detail": {"path": request.url.path},
                },
            },
        )
