from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from hashlib import sha256
import secrets
import smtplib
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation
from ..config import settings
from ..models.requests import CreateCompanyWithOwnerRequest
from .company_training_service import (
    CompanyAdminNotFoundError,
    CompanyNotFoundError,
    _fetch_active_training_groups_tx,
    _fetch_company_tx,
    _iso,
    _jsonb,
    _raise_company_unique_conflict,
    _record_activity_tx,
)
from .db import connect_dict, qualified_table


GENERIC_MAGIC_LINK_MESSAGE = (
    "Si existe una cuenta válida para ese email, te hemos enviado un enlace de acceso."
)


class CompanyAccountServiceError(RuntimeError):
    error_code = "company_account_service_error"


class CompanyMagicLinkNotFoundError(CompanyAccountServiceError):
    error_code = "company_magic_link_not_found"


class CompanyAdminInviteNotFoundError(CompanyAccountServiceError):
    error_code = "company_admin_invite_not_found"


class CompanySessionNotFoundError(CompanyAccountServiceError):
    error_code = "company_session_not_found"


def _now_dt() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _now_iso() -> str:
    return _now_dt().isoformat().replace("+00:00", "Z")


def _table_companies() -> str:
    return qualified_table("hrevn_start_companies")


def _table_company_admins() -> str:
    return qualified_table("hrevn_start_company_admins")


def _table_company_admin_invites() -> str:
    return qualified_table("hrevn_start_company_admin_invites")


def _table_magic_links() -> str:
    return qualified_table("hrevn_start_auth_magic_links")


def _table_sessions() -> str:
    return qualified_table("hrevn_start_auth_sessions")


def hash_token(raw_token: str) -> str:
    return sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(24)}"


def _make_magic_link_url(raw_token: str) -> str:
    return f"{settings.public_site_base_url}{settings.company_access_path_prefix}/?token={raw_token}"


def _make_company_admin_invite_url(raw_token: str) -> str:
    return f"{settings.public_site_base_url}{settings.company_invite_accept_path_prefix}/?token={raw_token}"


def _build_magic_link_email(company: dict[str, Any], admin: dict[str, Any], magic_link_url: str) -> EmailMessage:
    sender_name = company.get("display_name") or company["legal_name"]
    message = EmailMessage()
    message["From"] = settings.lead_email_sender
    message["To"] = admin["email"]
    message["Reply-To"] = settings.lead_email_recipient
    message["Subject"] = f"Acceso a {sender_name} en HREVN"
    body = f"""Hola {admin['full_name']},

Has solicitado un enlace de acceso para la cuenta de empresa "{sender_name}" en HREVN.

Abre este enlace para entrar:
{magic_link_url}

Este enlace es de un solo uso y caduca pronto.

Un saludo,
HREVN
"""
    message.set_content(body)
    return message


def _build_company_admin_invite_email(company: dict[str, Any], admin: dict[str, Any], invite_url: str) -> EmailMessage:
    sender_name = company.get("display_name") or company["legal_name"]
    message = EmailMessage()
    message["From"] = settings.lead_email_sender
    message["To"] = admin["email"]
    message["Reply-To"] = company.get("contact_email") or settings.lead_email_recipient
    message["Subject"] = f"Invitacion de acceso a {sender_name} en HREVN"
    body = f"""Hola {admin['full_name']},

Se ha creado tu acceso como representante de empresa para "{sender_name}" en HREVN.

Activa tu cuenta con este enlace:
{invite_url}

Este enlace es personal y caduca en breve.

Un saludo,
HREVN
"""
    message.set_content(body)
    return message


def _send_magic_link_email(company: dict[str, Any], admin: dict[str, Any], magic_link_url: str) -> tuple[str, str | None]:
    if not settings.lead_smtp_host:
        return "stored_only", "SMTP host not configured."

    message = _build_magic_link_email(company, admin, magic_link_url)
    recipients = [admin["email"]]
    try:
        if settings.lead_smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
                if settings.lead_smtp_username:
                    smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
                smtp.send_message(message, to_addrs=recipients)
            return "emailed", None

        with smtplib.SMTP(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
            if settings.lead_smtp_use_tls:
                smtp.starttls()
            if settings.lead_smtp_username:
                smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
            smtp.send_message(message, to_addrs=recipients)
        return "emailed", None
    except Exception as exc:
        return "stored_only", str(exc)


def _send_company_admin_invite_email(company: dict[str, Any], admin: dict[str, Any], invite_url: str) -> tuple[str, str | None]:
    if not settings.lead_smtp_host:
        return "stored_only", "SMTP host not configured."

    message = _build_company_admin_invite_email(company, admin, invite_url)
    recipients = [admin["email"]]
    try:
        if settings.lead_smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
                if settings.lead_smtp_username:
                    smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
                smtp.send_message(message, to_addrs=recipients)
            return "emailed", None

        with smtplib.SMTP(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
            if settings.lead_smtp_use_tls:
                smtp.starttls()
            if settings.lead_smtp_username:
                smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
            smtp.send_message(message, to_addrs=recipients)
        return "emailed", None
    except Exception as exc:
        return "stored_only", str(exc)


def _map_company_admin_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_admin_id": str(row["company_admin_id"]),
        "company_id": str(row["company_id"]),
        "status": row["status"],
        "access_level": row["access_level"],
        "full_name": row["full_name"],
        "email": row["email"],
        "job_title": row["job_title"],
        "invited_at": _iso(row["invited_at"]),
        "accepted_at": _iso(row["accepted_at"]),
        "last_seen_at": _iso(row["last_seen_at"]),
        "last_login_at": _iso(row["last_login_at"]),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _fetch_company_admin_tx(cur, company_admin_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          company_admin_id,
          company_id,
          status,
          access_level,
          full_name,
          email::text AS email,
          job_title,
          invited_at,
          accepted_at,
          last_seen_at,
          last_login_at,
          created_at,
          updated_at
        FROM {_table_company_admins()}
        WHERE company_admin_id = %s
        """,
        (company_admin_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyAdminNotFoundError(f"Company admin not found: {company_admin_id}")
    return _map_company_admin_row(row)


def _fetch_active_company_admins_by_email_tx(cur, email: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
          admin.company_admin_id,
          admin.company_id,
          admin.status,
          admin.access_level,
          admin.full_name,
          admin.email::text AS email,
          admin.job_title,
          admin.invited_at,
          admin.accepted_at,
          admin.last_seen_at,
          admin.last_login_at,
          admin.created_at,
          admin.updated_at
        FROM {_table_company_admins()} AS admin
        JOIN {_table_companies()} AS company
          ON company.company_id = admin.company_id
        WHERE admin.email = %s
          AND admin.status = 'active'
          AND company.status IN ('created', 'active')
        ORDER BY admin.created_at ASC
        """,
        (email,),
    )
    return [_map_company_admin_row(row) for row in cur.fetchall()]


def _fetch_magic_link_record_tx(cur, token_hash: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          link.auth_magic_link_id,
          link.company_admin_id,
          link.created_at,
          link.expires_at,
          link.used_at,
          link.revoked_at,
          link.request_ip,
          link.request_user_agent
        FROM {_table_magic_links()} AS link
        WHERE link.token_hash = %s
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyMagicLinkNotFoundError("Magic link is invalid or expired.")
    return {
        "auth_magic_link_id": str(row["auth_magic_link_id"]),
        "company_admin_id": str(row["company_admin_id"]),
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
        "used_at": _iso(row["used_at"]),
        "revoked_at": _iso(row["revoked_at"]),
        "request_ip": row["request_ip"],
        "request_user_agent": row["request_user_agent"],
    }


def _fetch_company_admin_invite_record_tx(cur, token_hash: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          invite.company_admin_invite_id,
          invite.company_id,
          invite.company_admin_id,
          invite.email::text AS email,
          invite.access_level,
          invite.created_at,
          invite.expires_at,
          invite.used_at,
          invite.revoked_at,
          invite.created_by_admin_id
        FROM {_table_company_admin_invites()} AS invite
        WHERE invite.token_hash = %s
        """,
        (token_hash,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyAdminInviteNotFoundError("Invite token is invalid or expired.")
    return {
        "company_admin_invite_id": str(row["company_admin_invite_id"]),
        "company_id": str(row["company_id"]),
        "company_admin_id": str(row["company_admin_id"]) if row["company_admin_id"] else None,
        "email": row["email"],
        "access_level": row["access_level"],
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
        "used_at": _iso(row["used_at"]),
        "revoked_at": _iso(row["revoked_at"]),
        "created_by_admin_id": str(row["created_by_admin_id"]) if row["created_by_admin_id"] else None,
    }


def _fetch_session_record_tx(cur, session_token_hash: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          auth_session_id,
          company_admin_id,
          created_at,
          expires_at,
          revoked_at,
          last_seen_at
        FROM {_table_sessions()}
        WHERE session_token_hash = %s
        """,
        (session_token_hash,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanySessionNotFoundError("Session is invalid or expired.")
    return {
        "auth_session_id": str(row["auth_session_id"]),
        "company_admin_id": str(row["company_admin_id"]),
        "created_at": _iso(row["created_at"]),
        "expires_at": _iso(row["expires_at"]),
        "revoked_at": _iso(row["revoked_at"]),
        "last_seen_at": _iso(row["last_seen_at"]),
    }


def _invalidate_previous_magic_links_tx(cur, company_admin_id: str, revoked_at: str) -> None:
    cur.execute(
        f"""
        UPDATE {_table_magic_links()}
        SET revoked_at = %s
        WHERE company_admin_id = %s
          AND used_at IS NULL
          AND revoked_at IS NULL
        """,
        (revoked_at, company_admin_id),
    )


def _invalidate_previous_admin_invites_tx(cur, company_admin_id: str, revoked_at: str) -> None:
    cur.execute(
        f"""
        UPDATE {_table_company_admin_invites()}
        SET revoked_at = %s
        WHERE company_admin_id = %s
          AND used_at IS NULL
          AND revoked_at IS NULL
        """,
        (revoked_at, company_admin_id),
    )


def _build_context_tx(cur, company_admin_id: str) -> dict[str, Any]:
    admin = _fetch_company_admin_tx(cur, company_admin_id)
    company = _fetch_company_tx(cur, admin["company_id"])
    active_training_groups = _fetch_active_training_groups_tx(cur, admin["company_id"])
    return {
        "company": company,
        "admin": admin,
        "active_training_groups": active_training_groups,
    }


def create_company_with_owner(
    request: CreateCompanyWithOwnerRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    company_id = str(uuid4())
    company_admin_id = str(uuid4())
    raw_invite_token = generate_token("adm")
    invite_url = _make_company_admin_invite_url(raw_invite_token)
    now = _now_dt()
    now_iso = now.isoformat().replace("+00:00", "Z")
    invite_expires_at = now + timedelta(hours=settings.company_admin_invite_ttl_hours)

    company: dict[str, Any] | None = None
    admin: dict[str, Any] | None = None
    with connect_dict() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"""
                    INSERT INTO {_table_companies()} (
                      company_id,
                      status,
                      legal_name,
                      tax_id,
                      display_name,
                      contact_email,
                      country_scope,
                      workforce_range,
                      current_policy_case_id,
                      metadata
                    )
                    VALUES (%s, 'created', %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        company_id,
                        request.legal_name,
                        request.tax_id,
                        request.display_name,
                        request.contact_email,
                        request.country_scope,
                        request.workforce_range,
                        request.current_policy_case_id,
                        _jsonb({"request_context": request_context, "page_url": request.page_url}),
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {_table_company_admins()} (
                      company_admin_id,
                      company_id,
                      status,
                      access_level,
                      full_name,
                      email,
                      job_title,
                      invited_at,
                      metadata
                    )
                    VALUES (%s, %s, 'invited', 'owner', %s, %s, %s, %s, %s)
                    """,
                    (
                        company_admin_id,
                        company_id,
                        request.owner_full_name,
                        request.owner_email,
                        request.owner_job_title,
                        now_iso,
                        _jsonb({"request_context": request_context, "page_url": request.page_url}),
                    ),
                )
            except UniqueViolation as exc:
                _raise_company_unique_conflict(exc, tax_id=request.tax_id, email=request.owner_email)
            cur.execute(
                f"""
                INSERT INTO {_table_company_admin_invites()} (
                  company_admin_invite_id,
                  company_id,
                  company_admin_id,
                  email,
                  access_level,
                  token_hash,
                  expires_at,
                  metadata
                )
                VALUES (%s, %s, %s, %s, 'owner', %s, %s, %s)
                """,
                (
                    str(uuid4()),
                    company_id,
                    company_admin_id,
                    request.owner_email,
                    hash_token(raw_invite_token),
                    invite_expires_at,
                    _jsonb({"request_context": request_context, "page_url": request.page_url}),
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "company_created",
                {
                    "legal_name": request.legal_name,
                    "tax_id": request.tax_id,
                    "contact_email": request.contact_email,
                },
                actor_type="system",
            )
            _record_activity_tx(
                cur,
                company_id,
                "company_owner_created",
                {
                    "company_admin_id": company_admin_id,
                    "email": request.owner_email,
                },
                actor_type="system",
                company_admin_id=company_admin_id,
            )
            _record_activity_tx(
                cur,
                company_id,
                "company_admin_invite_sent",
                {
                    "company_admin_id": company_admin_id,
                    "email": request.owner_email,
                    "access_level": "owner",
                },
                actor_type="system",
                company_admin_id=company_admin_id,
            )
            company = _fetch_company_tx(cur, company_id)
            admin = _fetch_company_admin_tx(cur, company_admin_id)

    if company and admin:
        delivery_status, email_error = _send_company_admin_invite_email(company, admin, invite_url)
        with connect_dict() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_table_company_admin_invites()}
                    SET metadata = jsonb_set(
                      COALESCE(metadata, '{{}}'::jsonb),
                      '{{delivery}}',
                      %s
                    )
                    WHERE company_admin_id = %s
                      AND used_at IS NULL
                      AND revoked_at IS NULL
                    """,
                    (
                        _jsonb(
                            {
                                "delivery_status": delivery_status,
                                "email_error": email_error,
                                "attempted_at": _now_iso(),
                            }
                        ),
                        admin["company_admin_id"],
                    ),
                )
                _record_activity_tx(
                    cur,
                    company["company_id"],
                    "company_admin_invite_delivery_updated",
                    {
                        "company_admin_id": admin["company_admin_id"],
                        "delivery_status": delivery_status,
                        "email_error": email_error,
                    },
                    actor_type="system",
                    company_admin_id=admin["company_admin_id"],
                )

    return {
        "company": company,
        "admin": admin,
    }


def accept_company_admin_invite(
    token: str,
    request_context: dict[str, str | None],
    *,
    page_url: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    now = _now_dt()
    now_iso = now.isoformat().replace("+00:00", "Z")
    token_hash = hash_token(token)

    with connect_dict() as conn:
        with conn.cursor() as cur:
            invite = _fetch_company_admin_invite_record_tx(cur, token_hash)
            if invite["used_at"] or invite["revoked_at"]:
                raise CompanyAdminInviteNotFoundError("Invite token is invalid or expired.")
            if invite["expires_at"] and invite["expires_at"] <= now_iso:
                raise CompanyAdminInviteNotFoundError("Invite token is invalid or expired.")
            if not invite["company_admin_id"]:
                raise CompanyAdminInviteNotFoundError("Invite token is invalid or expired.")

            admin = _fetch_company_admin_tx(cur, invite["company_admin_id"])
            company = _fetch_company_tx(cur, invite["company_id"])
            if admin["status"] not in {"invited", "active"}:
                raise CompanyAdminInviteNotFoundError("Invite token is invalid or expired.")

            _invalidate_previous_admin_invites_tx(cur, admin["company_admin_id"], now_iso)
            cur.execute(
                f"""
                UPDATE {_table_company_admins()}
                SET
                  status = 'active',
                  accepted_at = COALESCE(accepted_at, %s),
                  last_seen_at = %s
                WHERE company_admin_id = %s
                """,
                (now_iso, now_iso, admin["company_admin_id"]),
            )
            cur.execute(
                f"""
                UPDATE {_table_companies()}
                SET status = 'active'
                WHERE company_id = %s
                  AND status = 'created'
                """,
                (company["company_id"],),
            )
            cur.execute(
                f"""
                UPDATE {_table_company_admin_invites()}
                SET
                  used_at = %s,
                  revoked_at = NULL,
                  metadata = jsonb_set(
                    COALESCE(metadata, '{{}}'::jsonb),
                    '{{accepted}}',
                    %s
                  )
                WHERE company_admin_invite_id = %s
                """,
                (
                    now_iso,
                    _jsonb(
                        {
                            "accepted_at": now_iso,
                            "page_url": page_url,
                            "request_context": request_context,
                            "user_agent": user_agent or request_context.get("user_agent"),
                        }
                    ),
                    invite["company_admin_invite_id"],
                ),
            )
            _record_activity_tx(
                cur,
                company["company_id"],
                "company_admin_invite_accepted",
                {
                    "company_admin_id": admin["company_admin_id"],
                    "company_admin_invite_id": invite["company_admin_invite_id"],
                    "page_url": page_url,
                },
                actor_type="company_admin",
                company_admin_id=admin["company_admin_id"],
            )
            company = _fetch_company_tx(cur, company["company_id"])
            admin = _fetch_company_admin_tx(cur, admin["company_admin_id"])

    return {
        "company": company,
        "admin": admin,
    }


def request_magic_link(
    email: str,
    request_context: dict[str, str | None],
    *,
    page_url: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    now = _now_dt()
    now_iso = now.isoformat().replace("+00:00", "Z")
    with connect_dict() as conn:
        with conn.cursor() as cur:
            admins = _fetch_active_company_admins_by_email_tx(cur, email)
            for admin in admins:
                company = _fetch_company_tx(cur, admin["company_id"])
                _invalidate_previous_magic_links_tx(cur, admin["company_admin_id"], now_iso)
                raw_token = generate_token("mag")
                magic_link_url = _make_magic_link_url(raw_token)
                delivery_status, email_error = _send_magic_link_email(company, admin, magic_link_url)
                cur.execute(
                    f"""
                    INSERT INTO {_table_magic_links()} (
                      company_admin_id,
                      token_hash,
                      expires_at,
                      request_ip,
                      request_user_agent,
                      metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        admin["company_admin_id"],
                        hash_token(raw_token),
                        now + timedelta(minutes=settings.company_magic_link_ttl_minutes),
                        request_context.get("client_ip"),
                        user_agent or request_context.get("user_agent"),
                        _jsonb(
                            {
                                "page_url": page_url,
                                "request_context": request_context,
                                "delivery_status": delivery_status,
                                "email_error": email_error,
                            }
                        ),
                    ),
                )
                _record_activity_tx(
                    cur,
                    company["company_id"],
                    "company_admin_magic_link_requested",
                    {
                        "company_admin_id": admin["company_admin_id"],
                        "email": admin["email"],
                        "page_url": page_url,
                        "delivery_status": delivery_status,
                        "email_error": email_error,
                    },
                    actor_type="company_admin",
                    company_admin_id=admin["company_admin_id"],
                )
    return {
        "accepted": True,
        "message": GENERIC_MAGIC_LINK_MESSAGE,
    }


def consume_magic_link(
    token: str,
    request_context: dict[str, str | None],
    *,
    page_url: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    now = _now_dt()
    now_iso = now.isoformat().replace("+00:00", "Z")
    token_hash = hash_token(token)
    session_token = generate_token("sess")
    session_expires_at = now + timedelta(days=settings.company_session_ttl_days)

    with connect_dict() as conn:
        with conn.cursor() as cur:
            magic_link = _fetch_magic_link_record_tx(cur, token_hash)
            if magic_link["used_at"] or magic_link["revoked_at"]:
                raise CompanyMagicLinkNotFoundError("Magic link is invalid or expired.")
            if magic_link["expires_at"] and magic_link["expires_at"] <= now_iso:
                raise CompanyMagicLinkNotFoundError("Magic link is invalid or expired.")

            admin = _fetch_company_admin_tx(cur, magic_link["company_admin_id"])
            if admin["status"] != "active":
                raise CompanyMagicLinkNotFoundError("Magic link is invalid or expired.")

            company = _fetch_company_tx(cur, admin["company_id"])
            cur.execute(
                f"""
                UPDATE {_table_magic_links()}
                SET used_at = %s,
                    metadata = jsonb_set(
                      COALESCE(metadata, '{{}}'::jsonb),
                      '{{consumed}}',
                      %s
                    )
                WHERE auth_magic_link_id = %s
                """,
                (
                    now_iso,
                    _jsonb(
                        {
                            "consumed_at": now_iso,
                            "page_url": page_url,
                            "request_context": request_context,
                        }
                    ),
                    magic_link["auth_magic_link_id"],
                ),
            )
            cur.execute(
                f"""
                UPDATE {_table_company_admins()}
                SET
                  last_seen_at = %s,
                  last_login_at = %s
                WHERE company_admin_id = %s
                """,
                (now_iso, now_iso, admin["company_admin_id"]),
            )
            cur.execute(
                f"""
                INSERT INTO {_table_sessions()} (
                  company_admin_id,
                  session_token_hash,
                  expires_at,
                  last_seen_at,
                  created_ip,
                  created_user_agent,
                  metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    admin["company_admin_id"],
                    hash_token(session_token),
                    session_expires_at,
                    now_iso,
                    request_context.get("client_ip"),
                    user_agent or request_context.get("user_agent"),
                    _jsonb({"page_url": page_url, "request_context": request_context}),
                ),
            )
            _record_activity_tx(
                cur,
                company["company_id"],
                "company_admin_login_completed",
                {
                    "company_admin_id": admin["company_admin_id"],
                    "auth_magic_link_id": magic_link["auth_magic_link_id"],
                    "page_url": page_url,
                },
                actor_type="company_admin",
                company_admin_id=admin["company_admin_id"],
            )
            context = _build_context_tx(cur, admin["company_admin_id"])

    return {
        "session_token": session_token,
        "session_expires_at": session_expires_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "context": context,
    }


def get_authenticated_admin_context(
    session_token: str,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    if not session_token.strip():
        raise CompanySessionNotFoundError("Session is invalid or expired.")

    now = _now_dt()
    now_iso = now.isoformat().replace("+00:00", "Z")
    with connect_dict() as conn:
        with conn.cursor() as cur:
            session = _fetch_session_record_tx(cur, hash_token(session_token))
            if session["revoked_at"]:
                raise CompanySessionNotFoundError("Session is invalid or expired.")
            if session["expires_at"] and session["expires_at"] <= now_iso:
                raise CompanySessionNotFoundError("Session is invalid or expired.")

            admin = _fetch_company_admin_tx(cur, session["company_admin_id"])
            if admin["status"] != "active":
                raise CompanySessionNotFoundError("Session is invalid or expired.")

            cur.execute(
                f"""
                UPDATE {_table_sessions()}
                SET last_seen_at = %s
                WHERE auth_session_id = %s
                """,
                (now_iso, session["auth_session_id"]),
            )
            cur.execute(
                f"""
                UPDATE {_table_company_admins()}
                SET last_seen_at = %s
                WHERE company_admin_id = %s
                """,
                (now_iso, admin["company_admin_id"]),
            )
            context = _build_context_tx(cur, admin["company_admin_id"])

    return {
        "session_expires_at": session["expires_at"],
        "context": context,
    }
