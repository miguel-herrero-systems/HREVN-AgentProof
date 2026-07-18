from __future__ import annotations

from fastapi import APIRouter

from ..adapters.core_adapter import get_core_version
from ..config import settings
from ..models.responses import VersionResponse


router = APIRouter(tags=["version"])


@router.get("/v1/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(
        service_name=settings.service_name,
        service_version=settings.service_version,
        core_version=get_core_version(),
        toolkit_version="unknown",
    )

