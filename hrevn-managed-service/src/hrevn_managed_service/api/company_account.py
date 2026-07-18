from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status

from ..config import settings
from ..models.requests import (
    AcceptCompanyAdminInviteRequest,
    ConsumeCompanyMagicLinkRequest,
    CreateCompanyWithOwnerRequest,
    RequestCompanyMagicLinkRequest,
)
from ..models.responses import (
    CompanyAdminInviteResponse,
    CompanyAuthSessionResponse,
    CompanyCreateWithOwnerResponse,
    CompanyMagicLinkRequestResponse,
    CompanyMeResponse,
)
from ..services.company_account_service import (
    CompanyAdminInviteNotFoundError,
    CompanyMagicLinkNotFoundError,
    CompanySessionNotFoundError,
    accept_company_admin_invite,
    consume_magic_link,
    create_company_with_owner,
    get_authenticated_admin_context,
    request_magic_link,
)
from ..services.company_training_service import CompanyAdminEmailConflictError, CompanyTaxIdConflictError
from ..services.lead_service import validate_lead_origin


router = APIRouter(tags=["company_account"])


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


def _validate_origin(http_request: Request) -> None:
    origin = http_request.headers.get("origin")
    if not origin:
        raise _error(status.HTTP_403_FORBIDDEN, "missing_origin", "Origin header is required.")
    try:
        validate_lead_origin(origin)
    except ValueError as exc:
        raise _error(status.HTTP_403_FORBIDDEN, "origin_not_allowed", str(exc)) from exc


@router.post(
    "/v1/hrevn-start/company-account/company-with-owner",
    response_model=CompanyCreateWithOwnerResponse,
)
def create_company_account_with_owner(
    request: CreateCompanyWithOwnerRequest,
    http_request: Request,
) -> CompanyCreateWithOwnerResponse:
    _validate_origin(http_request)
    try:
        result = create_company_with_owner(request, _request_context(http_request))
    except (CompanyTaxIdConflictError, CompanyAdminEmailConflictError) as exc:
        raise _error(status.HTTP_409_CONFLICT, exc.error_code, str(exc)) from exc
    return CompanyCreateWithOwnerResponse(company=result["company"], admin=result["admin"])


@router.post(
    "/v1/hrevn-start/company-account/admin-invites/accept",
    response_model=CompanyAdminInviteResponse,
)
def accept_company_account_invite(
    request: AcceptCompanyAdminInviteRequest,
    http_request: Request,
) -> CompanyAdminInviteResponse:
    _validate_origin(http_request)
    try:
        result = accept_company_admin_invite(
            request.token,
            _request_context(http_request),
            page_url=request.page_url,
            user_agent=request.user_agent,
        )
    except CompanyAdminInviteNotFoundError as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, exc.error_code, str(exc)) from exc

    return CompanyAdminInviteResponse(company=result["company"], admin=result["admin"])


@router.post(
    "/v1/hrevn-start/company-account/auth/request-magic-link",
    response_model=CompanyMagicLinkRequestResponse,
)
def request_company_magic_link(
    request: RequestCompanyMagicLinkRequest,
    http_request: Request,
) -> CompanyMagicLinkRequestResponse:
    _validate_origin(http_request)
    result = request_magic_link(
        request.email,
        _request_context(http_request),
        page_url=request.page_url,
        user_agent=request.user_agent,
    )
    return CompanyMagicLinkRequestResponse(**result)


@router.post(
    "/v1/hrevn-start/company-account/auth/consume-magic-link",
    response_model=CompanyAuthSessionResponse,
)
def consume_company_magic_link(
    request: ConsumeCompanyMagicLinkRequest,
    response: Response,
    http_request: Request,
) -> CompanyAuthSessionResponse:
    _validate_origin(http_request)
    try:
        result = consume_magic_link(
            request.token,
            _request_context(http_request),
            page_url=request.page_url,
            user_agent=request.user_agent,
        )
    except CompanyMagicLinkNotFoundError as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, exc.error_code, str(exc)) from exc

    response.set_cookie(
        key=settings.company_auth_cookie_name,
        value=result["session_token"],
        max_age=settings.company_session_ttl_days * 24 * 60 * 60,
        expires=result["session_expires_at"],
        path="/",
        domain=settings.company_auth_cookie_domain or None,
        secure=settings.company_auth_cookie_secure,
        httponly=True,
        samesite=settings.company_auth_cookie_samesite,
    )
    return CompanyAuthSessionResponse(
        session_expires_at=result["session_expires_at"],
        context=result["context"],
    )


@router.get("/v1/hrevn-start/company-account/me", response_model=CompanyMeResponse)
def get_company_account_context(
    http_request: Request,
    session_token: str | None = Cookie(default=None, alias=settings.company_auth_cookie_name),
) -> CompanyMeResponse:
    _validate_origin(http_request)
    if not session_token:
        raise _error(status.HTTP_401_UNAUTHORIZED, "missing_company_session", "Missing company session.")
    try:
        result = get_authenticated_admin_context(session_token, _request_context(http_request))
    except CompanySessionNotFoundError as exc:
        raise _error(status.HTTP_401_UNAUTHORIZED, exc.error_code, str(exc)) from exc

    return CompanyMeResponse(context=result["context"])
