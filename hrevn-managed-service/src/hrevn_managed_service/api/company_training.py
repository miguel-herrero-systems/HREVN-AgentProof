from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from ..config import settings
from ..models.requests import (
    CompanyAdminCreateRequest,
    CompanyAdminUpdateRequest,
    CompanyCreateRequest,
    CompanyParticipantInviteAcceptRequest,
    CompanyParticipantCreateRequest,
    CompanyParticipantUpdateRequest,
    TrainingGroupCreateRequest,
    TrainingGroupExportCreateRequest,
    TrainingGroupParticipantsImportRequest,
    TrainingGroupUpdateRequest,
)
from ..models.responses import (
    CompanyAdminCreateResponse,
    CompanyAdminUpdateResponse,
    CompanyActivityLoadResponse,
    CompanyCreateResponse,
    CompanyParticipantInviteAcceptResponse,
    CompanyParticipantInviteLoadResponse,
    CompanyLoadResponse,
    CompanyParticipantCreateResponse,
    CompanyParticipantUpdateResponse,
    TrainingGroupCreateResponse,
    TrainingGroupExportCreateResponse,
    TrainingGroupLoadResponse,
    TrainingGroupParticipantsImportResponse,
    TrainingGroupUpdateResponse,
)
from ..services.company_training_service import (
    CompanyAdminEmailConflictError,
    CompanyAdminNotFoundError,
    CompanyNotFoundError,
    CompanyParticipantInviteNotFoundError,
    CompanyParticipantEmailConflictError,
    CompanyParticipantNotFoundError,
    CompanyTaxIdConflictError,
    TrainingGroupExportNotFoundError,
    TrainingGroupExportNotReadyError,
    TrainingGroupNotFoundError,
    accept_company_participant_invite,
    create_company,
    create_company_admin,
    create_company_participant,
    create_training_group,
    create_training_group_export,
    import_company_participants,
    load_company_participant_invite,
    load_company_activity,
    load_company,
    load_training_group,
    resolve_company_admin_company_id,
    resolve_company_participant_company_id,
    resolve_training_group_export_download,
    resolve_training_group_export_company_id,
    resolve_training_group_company_id,
    resend_company_participant_invite,
    resend_company_admin_invite,
    update_company_admin,
    update_company_participant,
    update_training_group,
)
from ..services.company_account_service import CompanySessionNotFoundError, get_authenticated_admin_context
from ..services.lead_service import validate_lead_origin


router = APIRouter(tags=["company_training"])


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


def _validate_origin_strict(http_request: Request) -> None:
    origin = http_request.headers.get("origin")
    if not origin:
        raise _error(status.HTTP_403_FORBIDDEN, "missing_origin", "Origin header is required.")
    try:
        validate_lead_origin(origin)
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc


def _require_authenticated_company_context(http_request: Request) -> dict[str, object]:
    _validate_origin_strict(http_request)
    session_token = http_request.cookies.get(settings.company_auth_cookie_name)
    if not session_token:
        raise _error(status.HTTP_401_UNAUTHORIZED, "missing_company_session", "Missing company session.")
    try:
        result = get_authenticated_admin_context(session_token, _request_context(http_request))
    except CompanySessionNotFoundError as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, exc.error_code, str(exc)) from exc
    return result["context"]


def _require_company_access(http_request: Request, company_id: str) -> dict[str, object]:
    context = _require_authenticated_company_context(http_request)
    context_company_id = context.get("company", {}).get("company_id")
    if context_company_id != company_id:
        raise _error(status.HTTP_404_NOT_FOUND, "company_not_found", f"Company not found: {company_id}")
    return context


def _require_training_group_access(
    http_request: Request,
    training_group_id: str,
    *,
    company_id: str | None = None,
) -> dict[str, object]:
    context = _require_authenticated_company_context(http_request)
    resource_company_id = resolve_training_group_company_id(training_group_id)
    context_company_id = context.get("company", {}).get("company_id")
    if resource_company_id != context_company_id or (company_id is not None and resource_company_id != company_id):
        raise _error(status.HTTP_404_NOT_FOUND, "training_group_not_found", f"Training group not found: {training_group_id}")
    return context


def _require_company_admin_access(http_request: Request, company_admin_id: str) -> dict[str, object]:
    context = _require_authenticated_company_context(http_request)
    resource_company_id = resolve_company_admin_company_id(company_admin_id)
    context_company_id = context.get("company", {}).get("company_id")
    if resource_company_id != context_company_id:
        raise _error(status.HTTP_404_NOT_FOUND, "company_admin_not_found", f"Company admin not found: {company_admin_id}")
    return context


def _require_company_participant_access(http_request: Request, company_participant_id: str) -> dict[str, object]:
    context = _require_authenticated_company_context(http_request)
    resource_company_id = resolve_company_participant_company_id(company_participant_id)
    context_company_id = context.get("company", {}).get("company_id")
    if resource_company_id != context_company_id:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "company_participant_not_found",
            f"Company participant not found: {company_participant_id}",
        )
    return context


def _require_export_access(http_request: Request, training_group_export_id: str) -> dict[str, object]:
    context = _require_authenticated_company_context(http_request)
    resource_company_id = resolve_training_group_export_company_id(training_group_export_id)
    context_company_id = context.get("company", {}).get("company_id")
    if resource_company_id != context_company_id:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "training_group_export_not_found",
            f"Training group export not found: {training_group_export_id}",
        )
    return context


def _require_access_level(context: dict[str, object], allowed_levels: set[str]) -> None:
    admin = context.get("admin", {})
    access_level = admin.get("access_level")
    if access_level not in allowed_levels:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "insufficient_company_permissions",
            "This account does not have permission to perform this action.",
        )


@router.post("/v1/hrevn-start/companies", response_model=CompanyCreateResponse)
def create_company_endpoint(request: CompanyCreateRequest, http_request: Request) -> CompanyCreateResponse:
    _validate_origin_strict(http_request)

    try:
        company = create_company(request, _request_context(http_request))
    except CompanyTaxIdConflictError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc
    return CompanyCreateResponse(company=company)


@router.get("/v1/hrevn-start/companies/{company_id}", response_model=CompanyLoadResponse)
def get_company(company_id: str, http_request: Request) -> CompanyLoadResponse:
    _require_company_access(http_request, company_id)

    try:
        result = load_company(company_id)
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return CompanyLoadResponse(
        company=result["company"],
        admins=result["admins"],
        active_training_groups=result["active_training_groups"],
    )


@router.get("/v1/hrevn-start/companies/{company_id}/activity", response_model=CompanyActivityLoadResponse)
def get_company_activity(
    company_id: str,
    http_request: Request,
    limit: int = 80,
) -> CompanyActivityLoadResponse:
    _require_company_access(http_request, company_id)

    safe_limit = max(1, min(limit, 200))
    try:
        result = load_company_activity(company_id, limit=safe_limit)
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return CompanyActivityLoadResponse(
        company=result["company"],
        activity=result["activity"],
    )


@router.post("/v1/hrevn-start/companies/{company_id}/admins", response_model=CompanyAdminCreateResponse)
def create_company_admin_endpoint(
    company_id: str,
    request: CompanyAdminCreateRequest,
    http_request: Request,
) -> CompanyAdminCreateResponse:
    context = _require_company_access(http_request, company_id)
    _require_access_level(context, {"owner"})

    try:
        result = create_company_admin(
            company_id,
            request,
            _request_context(http_request),
            created_by_admin_id=str(context.get("admin", {}).get("company_admin_id") or "") or None,
        )
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CompanyAdminEmailConflictError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_company_admin_create", str(exc)) from exc

    return CompanyAdminCreateResponse(company=result["company"], admin=result["admin"])


@router.patch("/v1/hrevn-start/company-admins/{company_admin_id}", response_model=CompanyAdminUpdateResponse)
def update_company_admin_endpoint(
    company_admin_id: str,
    request: CompanyAdminUpdateRequest,
    http_request: Request,
) -> CompanyAdminUpdateResponse:
    context = _require_company_admin_access(http_request, company_admin_id)
    _require_access_level(context, {"owner"})

    try:
        admin = update_company_admin(company_admin_id, request)
    except CompanyAdminNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_company_admin_update", str(exc)) from exc

    return CompanyAdminUpdateResponse(admin=admin)


@router.post("/v1/hrevn-start/company-admins/{company_admin_id}/invite", response_model=CompanyAdminUpdateResponse)
def resend_company_admin_invite_endpoint(
    company_admin_id: str,
    http_request: Request,
) -> CompanyAdminUpdateResponse:
    context = _require_company_admin_access(http_request, company_admin_id)
    _require_access_level(context, {"owner"})

    try:
        result = resend_company_admin_invite(
            company_admin_id,
            _request_context(http_request),
            created_by_admin_id=str(context.get("admin", {}).get("company_admin_id") or "") or None,
        )
    except CompanyAdminNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_409_CONFLICT, "company_admin_invite_resend_blocked", str(exc)) from exc

    return CompanyAdminUpdateResponse(admin=result["admin"])


@router.post(
    "/v1/hrevn-start/companies/{company_id}/training-groups",
    response_model=TrainingGroupCreateResponse,
)
def create_training_group_endpoint(
    company_id: str,
    request: TrainingGroupCreateRequest,
    http_request: Request,
) -> TrainingGroupCreateResponse:
    context = _require_company_access(http_request, company_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        result = create_training_group(company_id, request, _request_context(http_request))
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return TrainingGroupCreateResponse(company=result["company"], training_group=result["training_group"])


@router.get(
    "/v1/hrevn-start/companies/{company_id}/training-groups/{training_group_id}",
    response_model=TrainingGroupLoadResponse,
)
def get_training_group(company_id: str, training_group_id: str, http_request: Request) -> TrainingGroupLoadResponse:
    _require_training_group_access(http_request, training_group_id, company_id=company_id)

    try:
        result = load_training_group(company_id, training_group_id)
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except TrainingGroupNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return TrainingGroupLoadResponse(
        company=result["company"],
        training_group=result["training_group"],
        policy_document=result["policy_document"],
        participants=result["participants"],
        progress=result["progress"],
        exports=result["exports"],
    )


@router.patch(
    "/v1/hrevn-start/companies/{company_id}/training-groups/{training_group_id}",
    response_model=TrainingGroupUpdateResponse,
)
def patch_training_group(
    company_id: str,
    training_group_id: str,
    request: TrainingGroupUpdateRequest,
    http_request: Request,
) -> TrainingGroupUpdateResponse:
    context = _require_training_group_access(http_request, training_group_id, company_id=company_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        training_group = update_training_group(company_id, training_group_id, request)
    except CompanyNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except TrainingGroupNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_training_group_update", str(exc)) from exc

    return TrainingGroupUpdateResponse(training_group=training_group)


@router.post(
    "/v1/hrevn-start/training-groups/{training_group_id}/participants",
    response_model=CompanyParticipantCreateResponse,
)
def create_participant_endpoint(
    training_group_id: str,
    request: CompanyParticipantCreateRequest,
    http_request: Request,
) -> CompanyParticipantCreateResponse:
    context = _require_training_group_access(http_request, training_group_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        result = create_company_participant(training_group_id, request, _request_context(http_request))
    except TrainingGroupNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CompanyParticipantEmailConflictError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return CompanyParticipantCreateResponse(training_group=result["training_group"], participant=result["participant"])


@router.post(
    "/v1/hrevn-start/training-groups/{training_group_id}/participants/import",
    response_model=TrainingGroupParticipantsImportResponse,
)
def import_participants_endpoint(
    training_group_id: str,
    request: TrainingGroupParticipantsImportRequest,
    http_request: Request,
) -> TrainingGroupParticipantsImportResponse:
    context = _require_training_group_access(http_request, training_group_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        result = import_company_participants(training_group_id, request, _request_context(http_request))
    except TrainingGroupNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CompanyParticipantEmailConflictError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_training_group_import", str(exc)) from exc

    return TrainingGroupParticipantsImportResponse(
        training_group=result["training_group"],
        participants=result["participants"],
    )


@router.patch(
    "/v1/hrevn-start/company-participants/{company_participant_id}",
    response_model=CompanyParticipantUpdateResponse,
)
def patch_company_participant(
    company_participant_id: str,
    request: CompanyParticipantUpdateRequest,
    http_request: Request,
) -> CompanyParticipantUpdateResponse:
    context = _require_company_participant_access(http_request, company_participant_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        participant = update_company_participant(company_participant_id, request)
    except CompanyParticipantNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except CompanyParticipantEmailConflictError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_company_participant_update", str(exc)) from exc

    return CompanyParticipantUpdateResponse(participant=participant)


@router.post(
    "/v1/hrevn-start/company-participants/{company_participant_id}/invite",
    response_model=CompanyParticipantUpdateResponse,
)
def resend_company_participant_invite_endpoint(
    company_participant_id: str,
    http_request: Request,
) -> CompanyParticipantUpdateResponse:
    context = _require_company_participant_access(http_request, company_participant_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        participant = resend_company_participant_invite(company_participant_id)
    except CompanyParticipantNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_409_CONFLICT, "company_participant_invite_resend_blocked", str(exc)) from exc

    return CompanyParticipantUpdateResponse(participant=participant)


@router.get(
    "/v1/hrevn-start/invites/{invite_token}",
    response_model=CompanyParticipantInviteLoadResponse,
)
def get_company_participant_invite(invite_token: str, http_request: Request) -> CompanyParticipantInviteLoadResponse:
    _validate_origin_strict(http_request)

    try:
        result = load_company_participant_invite(invite_token)
    except CompanyParticipantInviteNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return CompanyParticipantInviteLoadResponse(
        company=result["company"],
        training_group=result["training_group"],
        participant=result["participant"],
    )


@router.post(
    "/v1/hrevn-start/invites/{invite_token}/accept",
    response_model=CompanyParticipantInviteAcceptResponse,
)
def accept_company_invite(
    invite_token: str,
    request: CompanyParticipantInviteAcceptRequest,
    http_request: Request,
) -> CompanyParticipantInviteAcceptResponse:
    _validate_origin_strict(http_request)

    try:
        result = accept_company_participant_invite(invite_token, request, _request_context(http_request))
    except CompanyParticipantInviteNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except ValueError as exc:
        raise _error(status.HTTP_409_CONFLICT, "invite_acceptance_blocked", str(exc)) from exc

    return CompanyParticipantInviteAcceptResponse(
        company=result["company"],
        training_group=result["training_group"],
        participant=result["participant"],
    )


@router.post(
    "/v1/hrevn-start/training-groups/{training_group_id}/exports",
    response_model=TrainingGroupExportCreateResponse,
)
def create_export_endpoint(
    training_group_id: str,
    request: TrainingGroupExportCreateRequest,
    http_request: Request,
) -> TrainingGroupExportCreateResponse:
    context = _require_training_group_access(http_request, training_group_id)
    _require_access_level(context, {"owner", "admin"})

    try:
        result = create_training_group_export(training_group_id, request, _request_context(http_request))
    except TrainingGroupNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc

    return TrainingGroupExportCreateResponse(training_group=result["training_group"], export=result["export"])


@router.get("/v1/hrevn-start/training-group-exports/{training_group_export_id}/download")
def download_training_group_export(training_group_export_id: str, http_request: Request):
    _require_export_access(http_request, training_group_export_id)

    try:
        path, filename, media_type = resolve_training_group_export_download(training_group_export_id)
    except TrainingGroupExportNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, exc.error_code, str(exc)) from exc
    except TrainingGroupExportNotReadyError as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc

    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
