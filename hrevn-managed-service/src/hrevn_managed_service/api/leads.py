from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ..models.requests import ContactRequest, LeadCaptureRequest
from ..models.responses import ContactCaptureResponse, LeadCaptureResponse
from ..services.lead_service import capture_contact_submission, capture_lead_submission, validate_lead_origin


router = APIRouter(tags=["leads"])


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


@router.post("/v1/lead-check", response_model=LeadCaptureResponse)
def capture_lead(request: LeadCaptureRequest, http_request: Request) -> LeadCaptureResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    if request.honey.strip():
        raise _error(status.HTTP_400_BAD_REQUEST, "spam_detected", "Spam protection field was filled.")

    if not request.answers:
        raise _error(status.HTTP_400_BAD_REQUEST, "missing_answers", "Questionnaire answers are required.")

    result = capture_lead_submission(request)
    return LeadCaptureResponse(
        submission_id=result.submission_id,
        delivery_status=result.delivery_status,
        email_error=result.email_error,
    )


@router.post("/v1/contact-request", response_model=ContactCaptureResponse)
def capture_contact(request: ContactRequest, http_request: Request) -> ContactCaptureResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    if request.honey.strip():
        raise _error(status.HTTP_400_BAD_REQUEST, "spam_detected", "Spam protection field was filled.")

    result = capture_contact_submission(request)
    return ContactCaptureResponse(
        submission_id=result.submission_id,
        delivery_status=result.delivery_status,
        email_error=result.email_error,
    )
