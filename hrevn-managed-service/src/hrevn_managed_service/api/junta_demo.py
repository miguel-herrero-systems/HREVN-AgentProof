from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from ..services.junta_demo_service import (
    JuntaDemoError,
    add_junta_photo,
    close_junta_event,
    create_junta_event,
    get_junta_asset,
    get_junta_event,
    get_junta_overview,
    get_public_junta_verify_record,
    resolve_junta_photo,
)


router = APIRouter(tags=["junta-demo"])


def _call_service(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except JuntaDemoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class JuntaDemoLocationRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    captured_at: str | None = None
    source: str = "browser"


class JuntaDemoEventCreateRequest(BaseModel):
    asset_id: str
    event_type: Literal["ENTRADA", "INCIDENCIA", "entrada", "incidencia"]
    performed_by: str
    summary: str | None = None
    location: JuntaDemoLocationRequest | None = None

    @field_validator("asset_id", "performed_by")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class JuntaDemoPhotoCreateRequest(BaseModel):
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


class JuntaDemoEventCloseRequest(BaseModel):
    summary: str | None = None


@router.get("/v1/junta-demo/overview")
def junta_demo_overview() -> dict[str, Any]:
    return _call_service(get_junta_overview)


@router.get("/v1/junta-demo/assets/{asset_id}")
def junta_demo_asset(asset_id: str) -> dict[str, Any]:
    return _call_service(get_junta_asset, asset_id)


@router.get("/v1/junta-demo/events/{event_id}")
def junta_demo_event(event_id: str) -> dict[str, Any]:
    return _call_service(get_junta_event, event_id)


@router.post("/v1/junta-demo/events")
def junta_demo_create_event(request: JuntaDemoEventCreateRequest) -> dict[str, Any]:
    return _call_service(
        create_junta_event,
        asset_id=request.asset_id,
        event_type=request.event_type,
        performed_by=request.performed_by,
        summary=request.summary,
        location=request.location.model_dump() if request.location else None,
    )


@router.post("/v1/junta-demo/events/{event_id}/photos")
def junta_demo_add_photo(event_id: str, request: JuntaDemoPhotoCreateRequest) -> dict[str, Any]:
    return _call_service(
        add_junta_photo,
        event_id=event_id,
        filename=request.filename,
        media_type=request.media_type,
        content_base64=request.content_base64,
    )


@router.post("/v1/junta-demo/events/{event_id}/close")
def junta_demo_close_event(event_id: str, request: JuntaDemoEventCloseRequest) -> dict[str, Any]:
    return _call_service(close_junta_event, event_id=event_id, summary=request.summary)


@router.get("/v1/public/junta-demo/events/{event_id}/verify-record")
def junta_demo_verify_record(event_id: str) -> dict[str, Any]:
    return _call_service(get_public_junta_verify_record, event_id)


@router.get("/v1/public/junta-demo/events/{event_id}/photos/{photo_id}")
def junta_demo_event_photo(event_id: str, photo_id: str) -> FileResponse:
    resolved = _call_service(resolve_junta_photo, event_id, photo_id)
    return FileResponse(
        path=resolved["path"],
        media_type=resolved["media_type"],
        filename=resolved["filename"],
    )
