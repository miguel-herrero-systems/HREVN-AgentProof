from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..models.requests import (
    PolicyCaseCreateRequest,
    PolicyCaseUpdateRequest,
    PolicyDocumentGenerateRequest,
    PolicyQuestionnaireSubmissionRequest,
)
from ..models.responses import (
    PolicyCaseCreateResponse,
    PolicyCaseLoadResponse,
    PolicyCaseUpdateResponse,
    PolicyDocumentGenerateResponse,
    PolicyDocumentIssueResponse,
    PolicyDocumentLoadResponse,
    PolicyDocumentVerifyResponse,
    PolicyQuestionnaireSubmissionCreateResponse,
)
from ..services.lead_service import validate_lead_origin
from ..services.policy_document_service import (
    PolicyDocumentIssueBlockedError,
    issue_policy_document,
    resolve_policy_document_download,
    verify_policy_document_artifact,
)
from ..services.policy_service import (
    PolicyCaseNotFoundError,
    PolicyDocumentNotFoundError,
    PolicySubmissionNotFoundError,
    create_policy_case,
    create_policy_questionnaire_submission,
    generate_policy_document,
    load_policy_case,
    load_policy_document,
    update_policy_case,
)


router = APIRouter(tags=["policy"])


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


@router.post("/v1/hrevn-start/policy-cases", response_model=PolicyCaseCreateResponse)
def create_case(request: PolicyCaseCreateRequest, http_request: Request) -> PolicyCaseCreateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    policy_case = create_policy_case(request, _request_context(http_request))
    return PolicyCaseCreateResponse(policy_case=policy_case)


@router.get("/v1/hrevn-start/policy-cases/{policy_case_id}", response_model=PolicyCaseLoadResponse)
def get_case(policy_case_id: str, http_request: Request) -> PolicyCaseLoadResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        result = load_policy_case(policy_case_id)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return PolicyCaseLoadResponse(
        policy_case=result["policy_case"],
        latest_submission=result["latest_submission"],
        current_policy_document=result["current_policy_document"],
    )


@router.patch("/v1/hrevn-start/policy-cases/{policy_case_id}", response_model=PolicyCaseUpdateResponse)
def patch_case(
    policy_case_id: str,
    request: PolicyCaseUpdateRequest,
    http_request: Request,
) -> PolicyCaseUpdateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        policy_case = update_policy_case(policy_case_id, request)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_policy_case_update", str(exc)) from exc

    return PolicyCaseUpdateResponse(policy_case=policy_case)


@router.post(
    "/v1/hrevn-start/policy-cases/{policy_case_id}/submissions",
    response_model=PolicyQuestionnaireSubmissionCreateResponse,
)
def submit_questionnaire(
    policy_case_id: str,
    request: PolicyQuestionnaireSubmissionRequest,
    http_request: Request,
) -> PolicyQuestionnaireSubmissionCreateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        result = create_policy_questionnaire_submission(policy_case_id, request, _request_context(http_request))
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_policy_submission", str(exc)) from exc

    return PolicyQuestionnaireSubmissionCreateResponse(
        policy_case=result["policy_case"],
        submission=result["submission"],
    )


@router.post(
    "/v1/hrevn-start/policy-cases/{policy_case_id}/documents",
    response_model=PolicyDocumentGenerateResponse,
)
def generate_document(
    policy_case_id: str,
    request: PolicyDocumentGenerateRequest,
    http_request: Request,
) -> PolicyDocumentGenerateResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        result = generate_policy_document(policy_case_id, request)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicySubmissionNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_policy_document_request", str(exc)) from exc

    return PolicyDocumentGenerateResponse(
        policy_case=result["policy_case"],
        policy_document=result["policy_document"],
    )


@router.get(
    "/v1/hrevn-start/policy-cases/{policy_case_id}/documents/{policy_document_id}",
    response_model=PolicyDocumentLoadResponse,
)
def get_document(policy_case_id: str, policy_document_id: str, http_request: Request) -> PolicyDocumentLoadResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        result = load_policy_document(policy_case_id, policy_document_id)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicyDocumentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return PolicyDocumentLoadResponse(
        policy_case=result["policy_case"],
        policy_document=result["policy_document"],
    )


@router.post(
    "/v1/hrevn-start/policy-cases/{policy_case_id}/documents/{policy_document_id}/issue",
    response_model=PolicyDocumentIssueResponse,
)
def issue_document(policy_case_id: str, policy_document_id: str, http_request: Request) -> PolicyDocumentIssueResponse:
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        result = issue_policy_document(policy_case_id, policy_document_id)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicyDocumentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicyDocumentIssueBlockedError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return PolicyDocumentIssueResponse(
        policy_case_id=policy_case_id,
        policy_document_id=policy_document_id,
        document_status=result["policy_document"]["status"],
        download_url=result["download_path"],
        policy_document=result["policy_document"],
    )


@router.get("/v1/hrevn-start/policy-cases/{policy_case_id}/documents/{policy_document_id}/download")
def download_document(policy_case_id: str, policy_document_id: str, http_request: Request):
    try:
        validate_lead_origin(http_request.headers.get("origin"))
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc

    try:
        path, filename = resolve_policy_document_download(policy_case_id, policy_document_id)
    except PolicyCaseNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicyDocumentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except PolicyDocumentIssueBlockedError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.get(
    "/v1/hrevn-start/policy-documents/{artifact_id}/verify",
    response_model=PolicyDocumentVerifyResponse,
)
def verify_document_artifact(artifact_id: str) -> PolicyDocumentVerifyResponse:
    try:
        policy_document = verify_policy_document_artifact(artifact_id)
    except PolicyDocumentNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return PolicyDocumentVerifyResponse(policy_document=policy_document)
