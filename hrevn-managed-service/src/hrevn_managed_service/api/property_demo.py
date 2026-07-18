from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from ..services.property_demo_service import (
    add_demo_finding,
    add_demo_photo,
    close_demo_visit,
    create_demo_visit,
    delete_demo_finding,
    get_demo_building,
    get_demo_overview,
    get_demo_unit,
    get_demo_visit,
    get_public_visit_verify_record,
    resolve_demo_photo,
    update_demo_space_check,
)


router = APIRouter(tags=["property-demo"])


class PropertyDemoVisitCreateRequest(BaseModel):
    class LocationRequest(BaseModel):
        latitude: float = Field(ge=-90, le=90)
        longitude: float = Field(ge=-180, le=180)
        accuracy_meters: float = Field(ge=0)
        captured_at: str | None = None

    unit_id: str
    visit_type: Literal["entry", "review", "exit"]
    performed_by: str
    tenant_present: bool = False
    location: LocationRequest

    @field_validator("unit_id", "performed_by")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class PropertyDemoSpaceUpdateRequest(BaseModel):
    general_status: Literal["ok", "observations", "needs_review"]
    notes: str | None = None


class PropertyDemoFindingCreateRequest(BaseModel):
    space_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    description: str

    @field_validator("space_id", "category", "description")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class PropertyDemoPhotoCreateRequest(BaseModel):
    space_id: str
    finding_id: str | None = None
    filename: str
    media_type: str | None = None
    content_base64: str

    @field_validator("space_id", "filename", "content_base64")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("This field is required.")
        return text


class PropertyDemoVisitCloseRequest(BaseModel):
    summary: str | None = None


@router.get("/v1/property-demo/building")
def property_demo_building() -> dict[str, Any]:
    return get_demo_building()


@router.get("/v1/property-demo/overview")
def property_demo_overview(manager_id: str | None = Query(default=None)) -> dict[str, Any]:
    return get_demo_overview(manager_id=manager_id)


@router.get("/v1/property-demo/units/{unit_id}")
def property_demo_unit(unit_id: str) -> dict[str, Any]:
    return get_demo_unit(unit_id)


@router.get("/v1/property-demo/visits/{visit_id}")
def property_demo_visit(visit_id: str) -> dict[str, Any]:
    return get_demo_visit(visit_id)


@router.post("/v1/property-demo/visits")
def property_demo_create_visit(request: PropertyDemoVisitCreateRequest) -> dict[str, Any]:
    return create_demo_visit(
        unit_id=request.unit_id,
        visit_type=request.visit_type,
        performed_by=request.performed_by,
        tenant_present=request.tenant_present,
        location=request.location.model_dump(),
    )


@router.patch("/v1/property-demo/visits/{visit_id}/spaces/{space_id}")
def property_demo_update_space(
    visit_id: str, space_id: str, request: PropertyDemoSpaceUpdateRequest
) -> dict[str, Any]:
    return update_demo_space_check(
        visit_id=visit_id,
        space_id=space_id,
        general_status=request.general_status,
        notes=request.notes,
    )


@router.post("/v1/property-demo/visits/{visit_id}/findings")
def property_demo_add_finding(visit_id: str, request: PropertyDemoFindingCreateRequest) -> dict[str, Any]:
    return add_demo_finding(
        visit_id=visit_id,
        space_id=request.space_id,
        category=request.category,
        severity=request.severity,
        description=request.description,
    )


@router.delete("/v1/property-demo/visits/{visit_id}/findings/{finding_id}")
def property_demo_delete_finding(visit_id: str, finding_id: str) -> dict[str, Any]:
    return delete_demo_finding(visit_id=visit_id, finding_id=finding_id)


@router.post("/v1/property-demo/visits/{visit_id}/photos")
def property_demo_add_photo(visit_id: str, request: PropertyDemoPhotoCreateRequest) -> dict[str, Any]:
    return add_demo_photo(
        visit_id=visit_id,
        space_id=request.space_id,
        finding_id=request.finding_id,
        filename=request.filename,
        media_type=request.media_type,
        content_base64=request.content_base64,
    )


@router.post("/v1/property-demo/visits/{visit_id}/close")
def property_demo_close_visit(visit_id: str, request: PropertyDemoVisitCloseRequest) -> dict[str, Any]:
    return close_demo_visit(visit_id=visit_id, summary=request.summary)


@router.get("/v1/public/property-demo/visits/{visit_id}/verify-record")
def property_demo_verify_record(visit_id: str) -> dict[str, Any]:
    return get_public_visit_verify_record(visit_id)


@router.get("/v1/public/property-demo/visits/{visit_id}/photos/{photo_id}")
def property_demo_visit_photo(visit_id: str, photo_id: str) -> FileResponse:
    resolved = resolve_demo_photo(visit_id, photo_id)
    return FileResponse(
        path=resolved["path"],
        media_type=resolved["media_type"],
        filename=resolved["filename"],
    )
