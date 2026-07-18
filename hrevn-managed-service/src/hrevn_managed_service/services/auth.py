from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from ..config import settings
from ..models.auth_models import ApiKeyRecord, AuthContext


def _error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "output_version": "1.0",
            "result": "ERROR",
            "error_code": error_code,
            "message": message,
        },
    )


def _resolve_api_key_record(api_key: str) -> ApiKeyRecord | None:
    for configured_key, raw_record in settings.api_keys.items():
        if secrets.compare_digest(api_key, configured_key):
            return ApiKeyRecord(**raw_record)
    return None


def resolve_auth_context(authorization: str | None = Header(default=None)) -> AuthContext:
    if not settings.require_api_key:
        return AuthContext(authenticated=False)

    if not authorization or not authorization.startswith("Bearer "):
        raise _error(status.HTTP_401_UNAUTHORIZED, "missing_api_key", "Missing API key.")

    api_key = authorization.removeprefix("Bearer ").strip()
    if not api_key:
        raise _error(status.HTTP_401_UNAUTHORIZED, "invalid_api_key", "Invalid API key.")

    if not settings.api_keys:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "api_key_registry_not_configured",
            "API key enforcement is enabled but no keys are configured.",
        )

    record = _resolve_api_key_record(api_key)
    if record is None or not record.active:
        raise _error(status.HTTP_401_UNAUTHORIZED, "invalid_api_key", "Invalid API key.")

    return AuthContext(
        authenticated=True,
        api_key_hint=api_key[:6],
        customer_id=record.customer_id,
        plan=record.plan,
        license_id=record.license_id,
    )
