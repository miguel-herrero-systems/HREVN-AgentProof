from __future__ import annotations

from fastapi import APIRouter, Depends

from ..models.auth_models import AuthContext
from ..models.requests import BaselineCheckRequest, ProfileValidateRequest
from ..models.responses import BaselineResponse, ProfileValidateResponse
from ..services.auth import resolve_auth_context
from ..services.baseline_service import run_baseline_check, run_profile_validate


router = APIRouter(tags=["baseline"])


@router.post("/v1/baseline-check", response_model=BaselineResponse)
def baseline_check(request: BaselineCheckRequest, _auth: AuthContext = Depends(resolve_auth_context)) -> BaselineResponse:
    result = run_baseline_check(
        task_type=request.task_type,
        profile=request.profile,
        record=request.record,
        metadata=request.metadata,
    )
    return BaselineResponse(
        result=result.result,
        profile_detected=result.profile_detected,
        readiness_level=result.readiness_level,
        missing_required_blocks=result.missing_required_blocks,
        risk_flags=result.risk_flags,
        recommended_next_step=result.recommended_next_step,
        remedy_payload=result.remedy_payload,
        check_id=result.check_id,
        checked_at=result.checked_at,
    )


@router.post("/v1/profile/validate", response_model=ProfileValidateResponse)
def profile_validate(request: ProfileValidateRequest, _auth: AuthContext = Depends(resolve_auth_context)) -> ProfileValidateResponse:
    result, validation_status = run_profile_validate(
        profile=request.profile,
        record=request.record,
        metadata=request.metadata,
    )
    return ProfileValidateResponse(
        profile=request.profile,
        validation_status=validation_status,
        readiness_level=result.readiness_level,
        warnings=result.risk_flags,
        details={
            "missing_required_blocks": result.missing_required_blocks,
            "risk_flags": result.risk_flags,
            "recommended_next_step": result.recommended_next_step,
            "profile_contract": getattr(result, "profile_contract", {}),
        },
    )
