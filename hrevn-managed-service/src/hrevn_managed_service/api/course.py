from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..models.requests import (
    CourseBlockAttemptRequest,
    CourseEnrollmentCreateRequest,
    CourseEnrollmentUpdateRequest,
)
from ..models.responses import (
    CourseBlockAttemptResponse,
    CourseCompleteResponse,
    CourseCertificateIssueResponse,
    CourseCertificateVerifyResponse,
    CourseEnrollmentCreateResponse,
    CourseEnrollmentLoadResponse,
    CourseEnrollmentUpdateResponse,
)
from ..services.course_certificate_service import (
    issue_course_certificate,
    resolve_course_certificate_download,
    verify_course_certificate_artifact,
)
from ..services.course_service import (
    CourseCompletionBlockedError,
    CourseEnrollmentNotFoundError,
    CourseInviteNotFoundError,
    complete_course_enrollment,
    create_course_enrollment,
    load_course_enrollment,
    record_course_block_attempt,
    update_course_enrollment,
)
from ..services.lead_service import validate_lead_origin


router = APIRouter(tags=["course"])


def _request_context(http_request: Request) -> dict[str, str | None]:
    forwarded_for = http_request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    real_ip = (http_request.headers.get("x-real-ip") or "").strip()
    client_ip = forwarded_for or real_ip or (http_request.client.host if http_request.client else None)
    user_agent = http_request.headers.get("user-agent")
    return {"client_ip": client_ip, "user_agent": user_agent}


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


@router.post("/v1/hrevn-start/course-enrollments", response_model=CourseEnrollmentCreateResponse)
def create_enrollment(
    request: CourseEnrollmentCreateRequest,
    http_request: Request,
) -> CourseEnrollmentCreateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        course = create_course_enrollment(request, _request_context(http_request))
    except CourseInviteNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_course_enrollment", str(exc)) from exc

    return CourseEnrollmentCreateResponse(course=course)


@router.get("/v1/hrevn-start/course-enrollments/{enrollment_id}", response_model=CourseEnrollmentLoadResponse)
def get_enrollment(enrollment_id: str, http_request: Request) -> CourseEnrollmentLoadResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        course = load_course_enrollment(enrollment_id)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return CourseEnrollmentLoadResponse(course=course)


@router.post(
    "/v1/hrevn-start/course-enrollments/{enrollment_id}/blocks/{block_code}/attempts",
    response_model=CourseBlockAttemptResponse,
)
def submit_block_attempt(
    enrollment_id: str,
    block_code: str,
    request: CourseBlockAttemptRequest,
    http_request: Request,
) -> CourseBlockAttemptResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        course = record_course_block_attempt(enrollment_id, block_code, request)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_course_attempt", str(exc)) from exc

    return CourseBlockAttemptResponse(
        enrollment_id=enrollment_id,
        block_code=block_code,
        attempt_number=request.attempt_number,
        passed=request.passed,
        score=request.score,
        course=course,
    )


@router.patch("/v1/hrevn-start/course-enrollments/{enrollment_id}", response_model=CourseEnrollmentUpdateResponse)
def patch_enrollment(
    enrollment_id: str,
    request: CourseEnrollmentUpdateRequest,
    http_request: Request,
) -> CourseEnrollmentUpdateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        course = update_course_enrollment(enrollment_id, request)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_course_update", str(exc)) from exc

    return CourseEnrollmentUpdateResponse(course=course)


@router.post(
    "/v1/hrevn-start/course-enrollments/{enrollment_id}/complete",
    response_model=CourseCompleteResponse,
)
def complete_enrollment(enrollment_id: str, http_request: Request) -> CourseCompleteResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        result = complete_course_enrollment(enrollment_id, _request_context(http_request))
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CourseCompletionBlockedError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return CourseCompleteResponse(
        enrollment_id=enrollment_id,
        certificate_status=result.certificate_status,
        completed_at=result.completed_at,
        review_recommendation=result.review_recommendation,
        course=result.course,
    )


@router.post(
    "/v1/hrevn-start/course-enrollments/{enrollment_id}/certificate",
    response_model=CourseCertificateIssueResponse,
)
def issue_enrollment_certificate(enrollment_id: str, http_request: Request) -> CourseCertificateIssueResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        result = issue_course_certificate(enrollment_id)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CourseCompletionBlockedError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return CourseCertificateIssueResponse(
        enrollment_id=enrollment_id,
        certificate_status=result["course"]["certificate_status"],
        download_url=result["download_path"],
        certificate_artifact=result["certificate_artifact"],
        course=result["course"],
    )


@router.get("/v1/hrevn-start/course-enrollments/{enrollment_id}/certificate/download")
def download_enrollment_certificate(enrollment_id: str, http_request: Request):
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc
    try:
        path, filename = resolve_course_certificate_download(enrollment_id)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CourseCompletionBlockedError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get(
    "/v1/hrevn-start/certificates/{artifact_id}/verify",
    response_model=CourseCertificateVerifyResponse,
)
def verify_enrollment_certificate(artifact_id: str) -> CourseCertificateVerifyResponse:
    try:
        certificate = verify_course_certificate_artifact(artifact_id)
    except CourseEnrollmentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return CourseCertificateVerifyResponse(certificate=certificate)
