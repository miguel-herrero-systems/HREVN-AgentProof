from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from ..services.promotora_demo_service import (
    PromotoraDemoError,
    add_promotora_photo,
    close_promotora_record,
    create_certificate,
    create_handover_review,
    get_promotora_overview,
    get_promotora_record,
    get_public_promotora_verify_record,
    resolve_promotora_photo,
)


router = APIRouter(tags=["promotora-demo"])


def _call_service(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except PromotoraDemoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class PartidaRequest(BaseModel):
    partida: str
    porcentaje: float = Field(ge=0, le=100)


class DefectRequest(BaseModel):
    item: str
    descripcion: str
    ubicacion: str
    estado: str

    @field_validator("item", "descripcion", "ubicacion", "estado")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class CertificateCreateRequest(BaseModel):
    promotion_id: str
    period: str
    global_progress_pct: float = Field(ge=0, le=100)
    certified_at: str
    certified_by: str
    partidas: list[PartidaRequest]

    @field_validator("promotion_id", "period", "certified_at", "certified_by")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class HandoverCreateRequest(BaseModel):
    promotion_id: str
    unit: str
    client: str
    reviewed_at: str
    reviewed_by: str
    defects: list[DefectRequest]

    @field_validator("promotion_id", "unit", "client", "reviewed_at", "reviewed_by")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class PhotoCreateRequest(BaseModel):
    filename: str
    media_type: str | None = None
    content_base64: str

    @field_validator("filename", "content_base64")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


@router.get("/v1/promotora-demo/overview")
def promotora_overview() -> dict[str, Any]:
    return _call_service(get_promotora_overview)


@router.get("/v1/promotora-demo/records/{record_id}")
def promotora_record(record_id: str) -> dict[str, Any]:
    return _call_service(get_promotora_record, record_id)


@router.post("/v1/promotora-demo/certificates")
def promotora_create_certificate(request: CertificateCreateRequest) -> dict[str, Any]:
    return _call_service(
        create_certificate,
        promotion_id=request.promotion_id,
        period=request.period,
        global_progress_pct=request.global_progress_pct,
        certified_at=request.certified_at,
        certified_by=request.certified_by,
        partidas=[item.model_dump() for item in request.partidas],
    )


@router.post("/v1/promotora-demo/handover-reviews")
def promotora_create_handover(request: HandoverCreateRequest) -> dict[str, Any]:
    return _call_service(
        create_handover_review,
        promotion_id=request.promotion_id,
        unit=request.unit,
        client=request.client,
        reviewed_at=request.reviewed_at,
        reviewed_by=request.reviewed_by,
        defects=[item.model_dump() for item in request.defects],
    )


@router.post("/v1/promotora-demo/records/{record_id}/photos")
def promotora_add_photo(record_id: str, request: PhotoCreateRequest) -> dict[str, Any]:
    return _call_service(
        add_promotora_photo,
        record_id=record_id,
        filename=request.filename,
        media_type=request.media_type,
        content_base64=request.content_base64,
    )


@router.post("/v1/promotora-demo/records/{record_id}/close")
def promotora_close_record(record_id: str) -> dict[str, Any]:
    return _call_service(close_promotora_record, record_id)


@router.get("/v1/public/promotora-demo/records/{record_id}/verify-record")
def promotora_verify_record(record_id: str) -> dict[str, Any]:
    return _call_service(get_public_promotora_verify_record, record_id)


@router.get("/v1/public/promotora-demo/records/{record_id}/photos/{photo_id}")
def promotora_photo(record_id: str, photo_id: str) -> FileResponse:
    resolved = _call_service(resolve_promotora_photo, record_id, photo_id)
    return FileResponse(
        path=resolved["path"],
        media_type=resolved["media_type"],
        filename=resolved["filename"],
    )
