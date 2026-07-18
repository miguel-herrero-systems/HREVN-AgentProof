from __future__ import annotations

from fastapi import APIRouter

from ..models.responses import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()

