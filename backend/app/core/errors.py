"""Typed application errors mapped to a consistent JSON envelope."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, detail: dict | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


class PermissionRequiredError(AppError):
    status_code = 403
    code = "permission_required"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


class NotConfiguredError(AppError):
    status_code = 400
    code = "not_configured"
