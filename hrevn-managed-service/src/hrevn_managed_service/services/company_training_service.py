from __future__ import annotations

import csv
from email.message import EmailMessage
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
import secrets
import smtplib
from typing import Any
from uuid import uuid4
import zipfile

from psycopg.errors import UniqueViolation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
from .course_certificate_service import resolve_course_certificate_download
from .course_service import REQUIRED_BLOCK_CODES, _build_certificate_artifact, _fetch_course_tx
from .db import connect_dict, qualified_table


class CompanyTrainingServiceError(RuntimeError):
    error_code = "company_training_service_error"


class CompanyNotFoundError(CompanyTrainingServiceError):
    error_code = "company_not_found"


class CompanyAdminNotFoundError(CompanyTrainingServiceError):
    error_code = "company_admin_not_found"


class TrainingGroupNotFoundError(CompanyTrainingServiceError):
    error_code = "training_group_not_found"


class TrainingGroupExportNotFoundError(CompanyTrainingServiceError):
    error_code = "training_group_export_not_found"


class TrainingGroupExportNotReadyError(CompanyTrainingServiceError):
    error_code = "training_group_export_not_ready"


class CompanyParticipantNotFoundError(CompanyTrainingServiceError):
    error_code = "company_participant_not_found"


class CompanyParticipantInviteNotFoundError(CompanyTrainingServiceError):
    error_code = "company_participant_invite_not_found"


class CompanyTaxIdConflictError(CompanyTrainingServiceError):
    error_code = "company_tax_id_conflict"


class CompanyAdminEmailConflictError(CompanyTrainingServiceError):
    error_code = "company_admin_email_conflict"


class CompanyParticipantEmailConflictError(CompanyTrainingServiceError):
    error_code = "company_participant_email_conflict"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _table_companies() -> str:
    return qualified_table("hrevn_start_companies")


def _table_company_admins() -> str:
    return qualified_table("hrevn_start_company_admins")


def _table_company_admin_invites() -> str:
    return qualified_table("hrevn_start_company_admin_invites")


def _table_training_groups() -> str:
    return qualified_table("hrevn_start_training_groups")


def _table_company_participants() -> str:
    return qualified_table("hrevn_start_company_participants")


def _table_exports() -> str:
    return qualified_table("hrevn_start_training_group_exports")


def _table_activity_log() -> str:
    return qualified_table("hrevn_start_company_activity_log")


def _table_enrollments() -> str:
    return qualified_table("hrevn_start_course_enrollments")


def _table_policy_cases() -> str:
    return qualified_table("hrevn_start_policy_cases")


def _table_policy_documents() -> str:
    return qualified_table("hrevn_start_policy_documents")


def _iso(value) -> str | None:
    if not value:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _exports_dir() -> Path:
    target = settings.course_storage_dir / "company-exports"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _make_invite_token() -> str:
    return f"inv_{secrets.token_urlsafe(12)}"


def _make_company_admin_invite_token() -> str:
    return f"adm_{secrets.token_urlsafe(24)}"


def _hash_token(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _make_course_invitation_url(language: str, invite_token: str) -> str:
    path_prefix = (
        settings.course_invitation_path_prefix_en
        if language == "en"
        else settings.course_invitation_path_prefix_es
    )
    return f"{settings.public_site_base_url}{path_prefix}/?invite_token={invite_token}"


def _make_company_admin_invitation_url(invite_token: str) -> str:
    return f"{settings.public_site_base_url}{settings.company_invite_accept_path_prefix}/?token={invite_token}"


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


def _build_company_participant_invite_email(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participant: dict[str, Any],
) -> EmailMessage:
    invite_url = participant["invite_url"]
    language = participant["language"]
    sender_name = company.get("display_name") or company["legal_name"]
    group_title = training_group["title"]

    message = EmailMessage()
    message["From"] = settings.lead_email_sender
    message["To"] = participant["email"]
    message["Reply-To"] = company.get("contact_email") or settings.lead_email_recipient
    if language == "en":
        message["Subject"] = f"{sender_name} invited you to HREVN Start training"
        body = f"""Hello {participant['full_name']},

{sender_name} invited you to complete the HREVN Start training group "{group_title}".

Open your individual access link:
{invite_url}

This link is personal and associated with your invitation record.

Best,
HREVN
"""
    else:
        message["Subject"] = f"{sender_name} te ha invitado a la formación HREVN Start"
        body = f"""Hola {participant['full_name']},

{sender_name} te ha invitado a completar la formación HREVN Start dentro del grupo "{group_title}".

Abre tu enlace individual de acceso:
{invite_url}

Este enlace es personal y queda asociado a tu registro de invitación.

Un saludo,
HREVN
"""
    message.set_content(body)
    return message


def _send_company_participant_invite_email(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participant: dict[str, Any],
) -> tuple[str, str | None]:
    if not settings.lead_smtp_host:
        return "stored_only", "SMTP host not configured."

    message = _build_company_participant_invite_email(company, training_group, participant)
    recipients = [participant["email"]]
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


def _record_activity_tx(
    cur,
    company_id: str,
    event_type: str,
    event_payload: dict[str, Any],
    *,
    actor_type: str = "system",
    training_group_id: str | None = None,
    company_participant_id: str | None = None,
    company_admin_id: str | None = None,
    course_enrollment_id: str | None = None,
) -> None:
    cur.execute(
        f"""
        INSERT INTO {_table_activity_log()} (
          company_activity_id,
          company_id,
          training_group_id,
          company_participant_id,
          company_admin_id,
          course_enrollment_id,
          event_type,
          event_payload,
          actor_type
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            company_id,
            training_group_id,
            company_participant_id,
            company_admin_id,
            course_enrollment_id,
            event_type,
            _jsonb(event_payload),
            actor_type,
        ),
    )


def _raise_company_unique_conflict(exc: UniqueViolation, *, email: str | None = None, tax_id: str | None = None) -> None:
    constraint_name = getattr(getattr(exc, "diag", None), "constraint_name", None)
    if constraint_name == "ux_hrevn_start_companies_tax_id":
        raise CompanyTaxIdConflictError(
            f"A company with tax ID {tax_id or 'provided'} already exists."
        ) from exc
    if constraint_name == "ux_hrevn_start_company_admins_company_email":
        raise CompanyAdminEmailConflictError(
            f"A company admin with email {email or 'provided'} already exists for this company."
        ) from exc
    if constraint_name == "ux_hrevn_start_company_participants_group_email":
        raise CompanyParticipantEmailConflictError(
            f"A participant with email {email or 'provided'} already exists in this training group."
        ) from exc
    raise exc


def _refresh_training_group_counts_tx(cur, training_group_id: str) -> None:
    cur.execute(
        f"""
        WITH stats AS (
          SELECT
            COUNT(*)::integer AS participant_count,
            COUNT(*) FILTER (WHERE status IN ('completed', 'certificate_issued'))::integer AS completed_count,
            COUNT(*) FILTER (WHERE status = 'certificate_issued')::integer AS certificate_issued_count
          FROM {_table_company_participants()}
          WHERE training_group_id = %s
        )
        UPDATE {_table_training_groups()} AS groups
        SET
          participant_count = stats.participant_count,
          completed_count = stats.completed_count,
          certificate_issued_count = stats.certificate_issued_count
        FROM stats
        WHERE groups.training_group_id = %s
        """,
        (training_group_id, training_group_id),
    )


def _fetch_company_tx(cur, company_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          company_id,
          status,
          legal_name,
          tax_id,
          display_name,
          contact_email::text AS contact_email,
          country_scope,
          workforce_range,
          current_policy_case_id,
          created_at,
          updated_at
        FROM {_table_companies()}
        WHERE company_id = %s
        """,
        (company_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyNotFoundError(f"Company not found: {company_id}")
    return {
        "company_id": str(row["company_id"]),
        "status": row["status"],
        "legal_name": row["legal_name"],
        "tax_id": row["tax_id"],
        "display_name": row["display_name"],
        "contact_email": row["contact_email"],
        "country_scope": row["country_scope"],
        "workforce_range": row["workforce_range"],
        "current_policy_case_id": str(row["current_policy_case_id"]) if row["current_policy_case_id"] else None,
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _fetch_company_admins_tx(cur, company_id: str) -> list[dict[str, Any]]:
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
        WHERE company_id = %s
        ORDER BY created_at ASC
        """,
        (company_id,),
    )
    return [_map_company_admin_row(row) for row in cur.fetchall()]


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


def _fetch_company_activity_tx(cur, company_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
          activity.company_activity_id,
          activity.company_id,
          activity.training_group_id,
          groups.title AS training_group_title,
          activity.company_participant_id,
          participant.full_name AS company_participant_name,
          activity.company_admin_id,
          admin.full_name AS company_admin_name,
          activity.course_enrollment_id,
          activity.event_type,
          activity.event_payload,
          activity.actor_type,
          activity.created_at
        FROM {_table_activity_log()} AS activity
        LEFT JOIN {_table_training_groups()} AS groups
          ON groups.training_group_id = activity.training_group_id
        LEFT JOIN {_table_company_participants()} AS participant
          ON participant.company_participant_id = activity.company_participant_id
        LEFT JOIN {_table_company_admins()} AS admin
          ON admin.company_admin_id = activity.company_admin_id
        WHERE activity.company_id = %s
        ORDER BY activity.created_at DESC
        LIMIT %s
        """,
        (company_id, limit),
    )
    return [
        {
            "company_activity_id": str(row["company_activity_id"]),
            "company_id": str(row["company_id"]),
            "training_group_id": str(row["training_group_id"]) if row["training_group_id"] else None,
            "training_group_title": row["training_group_title"],
            "company_participant_id": str(row["company_participant_id"]) if row["company_participant_id"] else None,
            "company_participant_name": row["company_participant_name"],
            "company_admin_id": str(row["company_admin_id"]) if row["company_admin_id"] else None,
            "company_admin_name": row["company_admin_name"],
            "course_enrollment_id": str(row["course_enrollment_id"]) if row["course_enrollment_id"] else None,
            "event_type": row["event_type"],
            "event_payload": row["event_payload"] or {},
            "actor_type": row["actor_type"],
            "created_at": _iso(row["created_at"]),
        }
        for row in cur.fetchall()
    ]


def _count_active_owner_admins_tx(cur, company_id: str) -> int:
    cur.execute(
        f"""
        SELECT COUNT(*)::integer AS owners_count
        FROM {_table_company_admins()}
        WHERE company_id = %s
          AND access_level = 'owner'
          AND status = 'active'
        """,
        (company_id,),
    )
    row = cur.fetchone()
    return int((row or {}).get("owners_count") or 0)


def _revoke_pending_company_admin_invites_tx(cur, company_admin_id: str, revoked_at: str) -> None:
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


def resolve_company_admin_company_id(company_admin_id: str) -> str:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            admin = _fetch_company_admin_tx(cur, company_admin_id)
            return str(admin["company_id"])


def _fetch_active_training_groups_tx(cur, company_id: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
          training_group_id,
          company_id,
          created_by_admin_id,
          policy_case_id,
          policy_document_id,
          status,
          title,
          description,
          course_version,
          default_language,
          planned_start_date,
          planned_end_date,
          launched_at,
          closed_at,
          participant_count,
          completed_count,
          certificate_issued_count,
          created_at,
          updated_at
        FROM {_table_training_groups()}
        WHERE company_id = %s
          AND status IN ('draft', 'inviting', 'in_progress', 'completed')
        ORDER BY created_at DESC
        """,
        (company_id,),
    )
    return [_map_training_group_row(row) for row in cur.fetchall()]


def _fetch_training_group_tx(cur, company_id: str, training_group_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          training_group_id,
          company_id,
          created_by_admin_id,
          policy_case_id,
          policy_document_id,
          status,
          title,
          description,
          course_version,
          default_language,
          planned_start_date,
          planned_end_date,
          launched_at,
          closed_at,
          participant_count,
          completed_count,
          certificate_issued_count,
          created_at,
          updated_at
        FROM {_table_training_groups()}
        WHERE company_id = %s
          AND training_group_id = %s
        """,
        (company_id, training_group_id),
    )
    row = cur.fetchone()
    if not row:
        raise TrainingGroupNotFoundError(f"Training group not found: {training_group_id}")
    return _map_training_group_row(row)


def resolve_training_group_company_id(training_group_id: str) -> str:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT company_id
                FROM {_table_training_groups()}
                WHERE training_group_id = %s
                """,
                (training_group_id,),
            )
            row = cur.fetchone()
            if not row:
                raise TrainingGroupNotFoundError(f"Training group not found: {training_group_id}")
            return str(row["company_id"])


def _fetch_company_participant_tx(cur, company_participant_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          participant.company_participant_id,
          participant.company_id,
          participant.training_group_id,
          participant.invited_by_admin_id,
          participant.course_enrollment_id,
          participant.status,
          participant.full_name,
          participant.email::text AS email,
          participant.role,
          participant.language,
          participant.employee_reference,
          participant.invite_token,
          participant.invited_at,
          participant.opened_at,
          participant.started_at,
          participant.completed_at,
          participant.certificate_issued_at,
          participant.last_seen_at,
          participant.created_at,
          participant.updated_at,
          participant.metadata AS participant_metadata,
          enrollment.enrollment_origin,
          enrollment.certificate_status,
          enrollment.metadata AS enrollment_metadata
        FROM {_table_company_participants()} AS participant
        LEFT JOIN {_table_enrollments()} AS enrollment
          ON enrollment.enrollment_id = participant.course_enrollment_id
        WHERE participant.company_participant_id = %s
        """,
        (company_participant_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyParticipantNotFoundError(f"Company participant not found: {company_participant_id}")
    return _map_company_participant_row(row)


def resolve_company_participant_company_id(company_participant_id: str) -> str:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            participant = _fetch_company_participant_tx(cur, company_participant_id)
            return str(participant["company_id"])


def _fetch_company_participant_by_invite_token_tx(cur, invite_token: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          participant.company_participant_id,
          participant.company_id,
          participant.training_group_id,
          participant.invited_by_admin_id,
          participant.course_enrollment_id,
          participant.status,
          participant.full_name,
          participant.email::text AS email,
          participant.role,
          participant.language,
          participant.employee_reference,
          participant.invite_token,
          participant.invited_at,
          participant.opened_at,
          participant.started_at,
          participant.completed_at,
          participant.certificate_issued_at,
          participant.last_seen_at,
          participant.created_at,
          participant.updated_at,
          participant.metadata AS participant_metadata,
          enrollment.enrollment_origin,
          enrollment.certificate_status,
          enrollment.metadata AS enrollment_metadata
        FROM {_table_company_participants()} AS participant
        LEFT JOIN {_table_enrollments()} AS enrollment
          ON enrollment.enrollment_id = participant.course_enrollment_id
        WHERE participant.invite_token = %s
        """,
        (invite_token,),
    )
    row = cur.fetchone()
    if not row:
        raise CompanyParticipantInviteNotFoundError(f"Invite not found: {invite_token}")
    return _map_company_participant_row(row)


def _fetch_group_participants_tx(cur, training_group_id: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
          participant.company_participant_id,
          participant.company_id,
          participant.training_group_id,
          participant.invited_by_admin_id,
          participant.course_enrollment_id,
          participant.status,
          participant.full_name,
          participant.email::text AS email,
          participant.role,
          participant.language,
          participant.employee_reference,
          participant.invite_token,
          participant.invited_at,
          participant.opened_at,
          participant.started_at,
          participant.completed_at,
          participant.certificate_issued_at,
          participant.last_seen_at,
          participant.created_at,
          participant.updated_at,
          participant.metadata AS participant_metadata,
          enrollment.enrollment_origin,
          enrollment.certificate_status,
          enrollment.metadata AS enrollment_metadata
        FROM {_table_company_participants()} AS participant
        LEFT JOIN {_table_enrollments()} AS enrollment
          ON enrollment.enrollment_id = participant.course_enrollment_id
        WHERE participant.training_group_id = %s
        ORDER BY participant.created_at ASC
        """,
        (training_group_id,),
    )
    return [_map_company_participant_row(row) for row in cur.fetchall()]


def _fetch_group_exports_tx(cur, training_group_id: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT
          training_group_export_id,
          company_id,
          training_group_id,
          requested_by_admin_id,
          export_kind,
          status,
          file_name,
          storage_path,
          sha256,
          metadata,
          generated_at,
          expires_at,
          created_at
        FROM {_table_exports()}
        WHERE training_group_id = %s
        ORDER BY created_at DESC
        """,
        (training_group_id,),
    )
    return [_map_export_row(row) for row in cur.fetchall()]


def _latest_exports_first(exports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        exports,
        key=lambda item: (item.get("generated_at") or item.get("created_at") or ""),
        reverse=True,
    )


def _fetch_export_tx(cur, training_group_export_id: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT
          training_group_export_id,
          company_id,
          training_group_id,
          requested_by_admin_id,
          export_kind,
          status,
          file_name,
          storage_path,
          sha256,
          metadata,
          generated_at,
          expires_at,
          created_at
        FROM {_table_exports()}
        WHERE training_group_export_id = %s
        """,
        (training_group_export_id,),
    )
    row = cur.fetchone()
    return _map_export_row(row)


def _slugify_filename(text: str) -> str:
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "hrevn-start"


def _export_download_path(training_group_export_id: str) -> str:
    return f"/v1/hrevn-start/training-group-exports/{training_group_export_id}/download"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_display_date(value: str | None) -> str:
    if not value:
        return "—"
    text = value.strip()
    if not text:
        return "—"
    try:
        normalized = text.replace("Z", "+00:00")
        date = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            date = datetime.fromisoformat(f"{text[:10]}T00:00:00+00:00")
        except ValueError:
            return text[:10] if len(text) >= 10 else text
    months = {
        1: "enero",
        2: "febrero",
        3: "marzo",
        4: "abril",
        5: "mayo",
        6: "junio",
        7: "julio",
        8: "agosto",
        9: "septiembre",
        10: "octubre",
        11: "noviembre",
        12: "diciembre",
    }
    return f"{date.day} de {months[date.month]} de {date.year}"


def _group_report_styles():
    styles = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#a5502c"),
            spaceAfter=6,
        ),
        "title": ParagraphStyle(
            "Title",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=colors.HexColor("#241b18"),
            spaceAfter=10,
        ),
        "lead": ParagraphStyle(
            "Lead",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11.2,
            leading=16,
            textColor=colors.HexColor("#5f5149"),
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=14.5,
            textColor=colors.HexColor("#4d433d"),
            spaceAfter=7,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#241b18"),
            spaceAfter=7,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9.2,
            leading=13,
            textColor=colors.HexColor("#6d6059"),
            spaceAfter=6,
        ),
    }


def _group_summary_table(rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    body = [[Paragraph(f"<b>{label}</b>", styles["body"]), Paragraph(value, styles["body"])] for label, value in rows]
    table = Table(body, colWidths=[52 * mm, 108 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdfa")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#e5d2c0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#efe3d7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _participants_report_table(participants: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> Table:
    body: list[list[Paragraph]] = [[
        Paragraph("<b>Participante</b>", styles["body"]),
        Paragraph("<b>Estado</b>", styles["body"]),
        Paragraph("<b>Idioma</b>", styles["body"]),
        Paragraph("<b>Certificado</b>", styles["body"]),
    ]]
    for participant in participants:
        artifact = participant.get("certificate_artifact") or {}
        body.append(
            [
                Paragraph(
                    f"{participant['full_name']}<br/><font size='9'>{participant['email']}</font>",
                    styles["body"],
                ),
                Paragraph(participant["status"], styles["body"]),
                Paragraph(participant["language"], styles["body"]),
                Paragraph(artifact.get("verification_code") or "—", styles["body"]),
            ]
        )
    table = Table(body, colWidths=[74 * mm, 30 * mm, 20 * mm, 36 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f6ece1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fffdfa")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#e5d2c0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#efe3d7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _training_group_bundle_gate(training_group: dict[str, Any], participants: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if not participants:
        return False, "Todavía no hay participantes cargados en el grupo."

    pending_completion = [
        participant for participant in participants if participant["status"] not in {"completed", "certificate_issued"}
    ]
    pending_certificates = [participant for participant in participants if participant["status"] == "completed"]

    if not pending_completion and not pending_certificates:
        return True, None

    reference_points = [
        _parse_iso_datetime(training_group.get("launched_at")),
        _parse_iso_datetime(training_group.get("created_at")),
    ]
    if training_group.get("planned_start_date"):
        reference_points.append(_parse_iso_datetime(f"{training_group['planned_start_date']}T00:00:00Z"))

    reference_points = [value for value in reference_points if value is not None]
    if reference_points:
        oldest_point = min(reference_points)
        if datetime.now(UTC) >= oldest_point + timedelta(days=30):
            return True, None
        deadline = oldest_point + timedelta(days=30)
        deadline_label = _format_display_date(deadline.isoformat().replace("+00:00", "Z"))
    else:
        deadline_label = None

    missing_bits: list[str] = []
    if pending_completion:
        count = len(pending_completion)
        missing_bits.append(
            f"Faltan {count} participante{'s' if count != 1 else ''} por completar la formación."
        )
    if pending_certificates:
        count = len(pending_certificates)
        missing_bits.append(
            f"Hay {count} certificado{'s' if count != 1 else ''} pendiente{'s' if count != 1 else ''} de emisión."
        )
    if deadline_label:
        missing_bits.append(f"Si el grupo no se cierra antes, el paquete se habilitará automáticamente el {deadline_label}.")

    return False, " ".join(missing_bits) if missing_bits else (
        "El paquete final estará disponible cuando el grupo quede cerrado o se alcance el plazo máximo."
    )


def _build_pending_bundle_export(training_group: dict[str, Any], availability_message: str) -> dict[str, Any]:
    return {
        "training_group_export_id": f"pending-{training_group['training_group_id']}",
        "company_id": training_group["company_id"],
        "training_group_id": training_group["training_group_id"],
        "requested_by_admin_id": None,
        "export_kind": "evidence_bundle",
        "status": "queued",
        "file_name": None,
        "download_url": None,
        "storage_path": None,
        "sha256": None,
        "availability_message": availability_message,
        "generated_at": None,
        "expires_at": None,
        "created_at": training_group.get("updated_at") or training_group.get("created_at") or _now_iso(),
    }


def _generate_bundle_export_now(
    *,
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
    export: dict[str, Any] | None,
) -> dict[str, Any]:
    if export is None:
        export_id = str(uuid4())
        with connect_dict() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_table_exports()} (
                      training_group_export_id,
                      company_id,
                      training_group_id,
                      export_kind,
                      status,
                      metadata
                    )
                    VALUES (%s, %s, %s, 'evidence_bundle', 'queued', %s)
                    """,
                    (
                        export_id,
                        company["company_id"],
                        training_group["training_group_id"],
                        _jsonb({"autogenerated": True, "requested_at": _now_iso()}),
                    ),
                )
                _record_activity_tx(
                    cur,
                    company["company_id"],
                    "training_group_export_requested",
                    {
                        "training_group_export_id": export_id,
                        "training_group_id": training_group["training_group_id"],
                        "export_kind": "evidence_bundle",
                        "auto_generated": True,
                    },
                    actor_type="system",
                    training_group_id=training_group["training_group_id"],
                )
                export = _fetch_export_tx(cur, export_id)

    try:
        file_name, relative_path, file_hash = _generate_training_group_export_file(
            export,
            company,
            training_group,
            participants,
        )
        return _mark_training_group_export_generated(
            export["training_group_export_id"],
            company_id=company["company_id"],
            training_group_id=training_group["training_group_id"],
            export_kind="evidence_bundle",
            file_name=file_name,
            relative_path=relative_path,
            file_hash=file_hash,
            participants_count=len(participants),
        )
    except Exception as exc:
        return _mark_training_group_export_failed(
            export["training_group_export_id"],
            company_id=company["company_id"],
            training_group_id=training_group["training_group_id"],
            export_kind="evidence_bundle",
            error_message=str(exc),
        )


def _resolve_group_bundle_exports(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bundle_ready, bundle_message = _training_group_bundle_gate(training_group, participants)
    bundle_exports = _latest_exports_first([item for item in exports if item["export_kind"] == "evidence_bundle"])

    if not bundle_ready:
        return [_build_pending_bundle_export(training_group, bundle_message or "Paquete final todavía no disponible.")]

    latest_bundle = bundle_exports[0] if bundle_exports else None
    if latest_bundle and latest_bundle["status"] == "generated" and latest_bundle.get("storage_path") and latest_bundle.get("file_name"):
        bundle_path = settings.course_storage_dir / latest_bundle["storage_path"]
        if bundle_path.exists():
            return [latest_bundle]

    generated_bundle = _generate_bundle_export_now(
        company=company,
        training_group=training_group,
        participants=participants,
        export=latest_bundle,
    )
    if generated_bundle["status"] != "generated":
        generated_bundle["download_url"] = None
        generated_bundle["availability_message"] = (
            "No se ha podido generar el paquete final. Reintenta o revisa logs."
        )
    return [generated_bundle]


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


def _map_training_group_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "training_group_id": str(row["training_group_id"]),
        "company_id": str(row["company_id"]),
        "created_by_admin_id": str(row["created_by_admin_id"]) if row["created_by_admin_id"] else None,
        "policy_case_id": str(row["policy_case_id"]) if row["policy_case_id"] else None,
        "policy_document_id": str(row["policy_document_id"]) if row["policy_document_id"] else None,
        "status": row["status"],
        "title": row["title"],
        "description": row["description"],
        "course_version": row["course_version"],
        "default_language": row["default_language"],
        "planned_start_date": str(row["planned_start_date"]) if row["planned_start_date"] else None,
        "planned_end_date": str(row["planned_end_date"]) if row["planned_end_date"] else None,
        "launched_at": _iso(row["launched_at"]),
        "closed_at": _iso(row["closed_at"]),
        "participant_count": int(row["participant_count"] or 0),
        "completed_count": int(row["completed_count"] or 0),
        "certificate_issued_count": int(row["certificate_issued_count"] or 0),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _map_company_participant_row(row: dict[str, Any]) -> dict[str, Any]:
    enrollment_metadata = row.get("enrollment_metadata") or {}
    participant_metadata = row.get("participant_metadata") or {}
    invite_delivery = participant_metadata.get("invite_delivery") or {}
    certificate_status = row.get("certificate_status")
    certificate_artifact = (
        _build_certificate_artifact(enrollment_metadata)
        if enrollment_metadata and certificate_status == "issued"
        else None
    )
    if certificate_artifact and not any(certificate_artifact.values()):
        certificate_artifact = None
    invite_url = _make_course_invitation_url(row["language"], row["invite_token"])
    certificate_download_url = None
    if row["course_enrollment_id"]:
        certificate_download_url = (
            f"/v1/hrevn-start/course-enrollments/{row['course_enrollment_id']}/certificate/download"
        )
    return {
        "company_participant_id": str(row["company_participant_id"]),
        "company_id": str(row["company_id"]),
        "training_group_id": str(row["training_group_id"]),
        "invited_by_admin_id": str(row["invited_by_admin_id"]) if row["invited_by_admin_id"] else None,
        "course_enrollment_id": str(row["course_enrollment_id"]) if row["course_enrollment_id"] else None,
        "status": row["status"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "language": row["language"],
        "employee_reference": row["employee_reference"],
        "invite_token": row["invite_token"],
        "invite_url": invite_url,
        "invite_delivery_status": invite_delivery.get("status") or "not_requested",
        "invite_email_error": invite_delivery.get("email_error"),
        "certificate_download_url": certificate_download_url,
        "invited_at": _iso(row["invited_at"]),
        "opened_at": _iso(row["opened_at"]),
        "started_at": _iso(row["started_at"]),
        "completed_at": _iso(row["completed_at"]),
        "certificate_issued_at": _iso(row["certificate_issued_at"]),
        "last_seen_at": _iso(row["last_seen_at"]),
        "enrollment_origin": row.get("enrollment_origin"),
        "certificate_artifact": certificate_artifact,
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _score_to_percent(score: int | None) -> int | None:
    if score is None:
        return None
    return max(0, min(100, int(score) * 20))


def _build_participant_progress_item(participant: dict[str, Any], course: dict[str, Any] | None) -> dict[str, Any]:
    block_codes = list(REQUIRED_BLOCK_CODES)
    optional_block_6_enabled = bool(course.get("optional_block_6_enabled")) if course else False
    if optional_block_6_enabled:
        block_codes.append("block_6")

    course_blocks = course.get("blocks", {}) if course else {}
    blocks: list[dict[str, Any]] = []
    for block_code in block_codes:
        block_state = course_blocks.get(block_code) or {}
        best_score = block_state.get("best_score")
        last_score = block_state.get("last_score")
        blocks.append(
            {
                "block_code": block_code,
                "is_optional": block_code == "block_6",
                "passed": bool(block_state.get("passed")),
                "attempts_count": int(block_state.get("attempts_count") or 0),
                "best_score": int(best_score) if best_score is not None else None,
                "best_score_percent": _score_to_percent(best_score),
                "last_score": int(last_score) if last_score is not None else None,
                "last_score_percent": _score_to_percent(last_score),
                "updated_at": block_state.get("updated_at"),
            }
        )

    return {
        "company_participant_id": participant["company_participant_id"],
        "course_enrollment_id": participant.get("course_enrollment_id"),
        "full_name": participant["full_name"],
        "email": participant["email"],
        "status": participant["status"],
        "required_course_completed": bool(course.get("required_course_completed")) if course else False,
        "optional_block_6_enabled": optional_block_6_enabled,
        "current_block_code": course.get("current_block_code") if course else None,
        "blocks": blocks,
    }


def _build_training_group_progress_tx(cur, participants: list[dict[str, Any]]) -> dict[str, Any]:
    progress_items: list[dict[str, Any]] = []
    include_optional_block_6 = False

    for participant in participants:
        course = None
        enrollment_id = participant.get("course_enrollment_id")
        if enrollment_id:
            course = _fetch_course_tx(cur, enrollment_id)
        progress_item = _build_participant_progress_item(participant, course)
        if progress_item["optional_block_6_enabled"]:
            include_optional_block_6 = True
        progress_items.append(progress_item)

    visible_block_codes = list(REQUIRED_BLOCK_CODES)
    if include_optional_block_6:
        visible_block_codes.append("block_6")

    return {
        "visible_block_codes": visible_block_codes,
        "participants": progress_items,
    }


def _map_export_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    metadata = row.get("metadata") or {}
    download_url = None
    if row["status"] == "generated" and row["storage_path"] and row["file_name"]:
        download_url = _export_download_path(str(row["training_group_export_id"]))
    return {
        "training_group_export_id": str(row["training_group_export_id"]),
        "company_id": str(row["company_id"]),
        "training_group_id": str(row["training_group_id"]),
        "requested_by_admin_id": str(row["requested_by_admin_id"]) if row["requested_by_admin_id"] else None,
        "export_kind": row["export_kind"],
        "status": row["status"],
        "file_name": row["file_name"],
        "download_url": download_url,
        "storage_path": row["storage_path"],
        "sha256": row["sha256"],
        "availability_message": metadata.get("availability_message"),
        "generated_at": _iso(row["generated_at"]),
        "expires_at": _iso(row["expires_at"]),
        "created_at": _iso(row["created_at"]),
    }


def _fetch_policy_case_current_document_id_tx(cur, policy_case_id: str) -> str | None:
    cur.execute(
        f"""
        SELECT current_policy_document_id
        FROM {_table_policy_cases()}
        WHERE policy_case_id = %s
        """,
        (policy_case_id,),
    )
    row = cur.fetchone()
    if not row or not row["current_policy_document_id"]:
        return None
    return str(row["current_policy_document_id"])


def _fetch_policy_document_summary_tx(cur, policy_document_id: str) -> dict[str, Any] | None:
    cur.execute(
        f"""
        SELECT
          policy_document_id,
          policy_case_id,
          language,
          policy_version,
          status,
          title,
          issued_at,
          artifact_id,
          verification_code,
          verification_url
        FROM {_table_policy_documents()}
        WHERE policy_document_id = %s
        """,
        (policy_document_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    policy_case_id = str(row["policy_case_id"])
    policy_document_id = str(row["policy_document_id"])
    return {
        "policy_case_id": policy_case_id,
        "policy_document_id": policy_document_id,
        "status": row["status"],
        "language": row["language"],
        "policy_version": row["policy_version"],
        "title": row["title"],
        "issued_at": _iso(row["issued_at"]),
        "download_url": f"/v1/hrevn-start/policy-cases/{policy_case_id}/documents/{policy_document_id}/download",
        "verification_code": row["verification_code"],
        "verification_url": row["verification_url"],
    }


def _resolve_group_policy_document_tx(
    cur,
    company: dict[str, Any],
    training_group: dict[str, Any],
) -> dict[str, Any] | None:
    policy_document_id = training_group.get("policy_document_id")
    if policy_document_id:
        return _fetch_policy_document_summary_tx(cur, policy_document_id)

    policy_case_id = training_group.get("policy_case_id") or company.get("current_policy_case_id")
    if not policy_case_id:
        return None

    current_document_id = _fetch_policy_case_current_document_id_tx(cur, policy_case_id)
    if not current_document_id:
        return None

    return _fetch_policy_document_summary_tx(cur, current_document_id)


def _record_participant_invite_delivery(
    company_id: str,
    training_group_id: str,
    company_participant_id: str,
    *,
    delivery_status: str,
    email_error: str | None,
    invite_url: str,
) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_table_company_participants()}
                SET
                  metadata = jsonb_set(
                    COALESCE(metadata, '{{}}'::jsonb),
                    '{{invite_delivery}}',
                    %s
                  )
                WHERE company_participant_id = %s
                """,
                (
                    _jsonb(
                        {
                            "status": delivery_status,
                            "email_error": email_error,
                            "invite_url": invite_url,
                            "attempted_at": _now_iso(),
                        }
                    ),
                    company_participant_id,
                ),
            )
            event_type = "company_participant_invite_emailed" if delivery_status == "emailed" else "company_participant_invite_failed"
            _record_activity_tx(
                cur,
                company_id,
                event_type,
                {
                    "company_participant_id": company_participant_id,
                    "delivery_status": delivery_status,
                    "email_error": email_error,
                },
                actor_type="system",
                training_group_id=training_group_id,
                company_participant_id=company_participant_id,
            )
            return _fetch_company_participant_tx(cur, company_participant_id)


def _deliver_company_participant_invite(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participant: dict[str, Any],
) -> dict[str, Any]:
    delivery_status, email_error = _send_company_participant_invite_email(company, training_group, participant)
    return _record_participant_invite_delivery(
        company["company_id"],
        training_group["training_group_id"],
        participant["company_participant_id"],
        delivery_status=delivery_status,
        email_error=email_error,
        invite_url=participant["invite_url"],
    )


def create_company(request: CompanyCreateRequest, request_context: dict[str, str | None]) -> dict[str, Any]:
    company_id = str(uuid4())
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
                        _jsonb({"request_context": request_context}),
                    ),
                )
            except UniqueViolation as exc:
                _raise_company_unique_conflict(exc, tax_id=request.tax_id)
            _record_activity_tx(
                cur,
                company_id,
                "company_created",
                {
                    "legal_name": request.legal_name,
                    "tax_id": request.tax_id,
                    "contact_email": request.contact_email,
                },
                actor_type="company_admin",
            )
            return _fetch_company_tx(cur, company_id)


def load_company(company_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company = _fetch_company_tx(cur, company_id)
            admins = _fetch_company_admins_tx(cur, company_id)
            active_groups = _fetch_active_training_groups_tx(cur, company_id)
            return {
                "company": company,
                "admins": admins,
                "active_training_groups": active_groups,
            }


def load_company_activity(company_id: str, *, limit: int = 100) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company = _fetch_company_tx(cur, company_id)
            activity = _fetch_company_activity_tx(cur, company_id, limit=limit)
            return {
                "company": company,
                "activity": activity,
            }


def create_company_admin(
    company_id: str,
    request: CompanyAdminCreateRequest,
    request_context: dict[str, str | None],
    *,
    created_by_admin_id: str | None = None,
) -> dict[str, Any]:
    company_admin_id = str(uuid4())
    invite_id = str(uuid4())
    raw_invite_token = _make_company_admin_invite_token()
    invite_url = _make_company_admin_invitation_url(raw_invite_token)
    now_dt = datetime.now(UTC).replace(microsecond=0)
    now = now_dt.isoformat().replace("+00:00", "Z")
    invite_expires_at = now_dt + timedelta(hours=settings.company_admin_invite_ttl_hours)
    if not request.send_invite:
        raise ValueError("Secondary company admins must activate their access from an invitation.")

    admin: dict[str, Any] | None = None
    company: dict[str, Any] | None = None
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company = _fetch_company_tx(cur, company_id)
            try:
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
                      accepted_at,
                      metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        company_admin_id,
                        company_id,
                        "invited",
                        request.access_level,
                        request.full_name,
                        request.email,
                        request.job_title,
                        now,
                        None,
                        _jsonb({"request_context": request_context, "send_invite": True}),
                    ),
                )
            except UniqueViolation as exc:
                _raise_company_unique_conflict(exc, email=request.email)
            cur.execute(
                f"""
                INSERT INTO {_table_company_admin_invites()} (
                  company_admin_invite_id,
                  company_id,
                  company_admin_id,
                  created_by_admin_id,
                  email,
                  access_level,
                  token_hash,
                  expires_at,
                  metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invite_id,
                    company_id,
                    company_admin_id,
                    created_by_admin_id,
                    request.email,
                    request.access_level,
                    _hash_token(raw_invite_token),
                    invite_expires_at,
                    _jsonb({"request_context": request_context, "invite_url": invite_url}),
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "company_admin_created",
                {
                    "company_admin_id": company_admin_id,
                    "email": request.email,
                    "access_level": request.access_level,
                    "send_invite": True,
                },
                actor_type="company_admin",
                company_admin_id=company_admin_id,
            )
            _record_activity_tx(
                cur,
                company_id,
                "company_admin_invite_sent",
                {
                    "company_admin_id": company_admin_id,
                    "company_admin_invite_id": invite_id,
                    "email": request.email,
                    "access_level": request.access_level,
                },
                actor_type="company_admin",
                company_admin_id=company_admin_id,
            )
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
                    WHERE company_admin_invite_id = %s
                    """,
                    (
                        _jsonb(
                            {
                                "delivery_status": delivery_status,
                                "email_error": email_error,
                                "attempted_at": _now_iso(),
                            }
                        ),
                        invite_id,
                    ),
                )
                _record_activity_tx(
                    cur,
                    company_id,
                    "company_admin_invite_delivery_updated",
                    {
                        "company_admin_id": company_admin_id,
                        "company_admin_invite_id": invite_id,
                        "delivery_status": delivery_status,
                        "email_error": email_error,
                    },
                    actor_type="company_admin",
                    company_admin_id=company_admin_id,
                )

    return {"company": company, "admin": admin}


def resend_company_admin_invite(
    company_admin_id: str,
    request_context: dict[str, str | None],
    *,
    created_by_admin_id: str | None = None,
) -> dict[str, Any]:
    invite_id = str(uuid4())
    raw_invite_token = _make_company_admin_invite_token()
    invite_url = _make_company_admin_invitation_url(raw_invite_token)
    now_dt = datetime.now(UTC).replace(microsecond=0)
    now = now_dt.isoformat().replace("+00:00", "Z")
    invite_expires_at = now_dt + timedelta(hours=settings.company_admin_invite_ttl_hours)

    admin: dict[str, Any] | None = None
    company: dict[str, Any] | None = None
    with connect_dict() as conn:
        with conn.cursor() as cur:
            admin = _fetch_company_admin_tx(cur, company_admin_id)
            if admin["status"] != "invited":
                raise ValueError("Only invited representatives can receive a new invitation.")
            company = _fetch_company_tx(cur, admin["company_id"])
            _revoke_pending_company_admin_invites_tx(cur, company_admin_id, now)
            cur.execute(
                f"""
                INSERT INTO {_table_company_admin_invites()} (
                  company_admin_invite_id,
                  company_id,
                  company_admin_id,
                  created_by_admin_id,
                  email,
                  access_level,
                  token_hash,
                  expires_at,
                  metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invite_id,
                    admin["company_id"],
                    company_admin_id,
                    created_by_admin_id,
                    admin["email"],
                    admin["access_level"],
                    _hash_token(raw_invite_token),
                    invite_expires_at,
                    _jsonb({"request_context": request_context, "invite_url": invite_url, "resend": True}),
                ),
            )
            _record_activity_tx(
                cur,
                admin["company_id"],
                "company_admin_invite_resent",
                {
                    "company_admin_id": company_admin_id,
                    "company_admin_invite_id": invite_id,
                    "email": admin["email"],
                },
                actor_type="company_admin",
                company_admin_id=company_admin_id,
            )

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
                    WHERE company_admin_invite_id = %s
                    """,
                    (
                        _jsonb(
                            {
                                "delivery_status": delivery_status,
                                "email_error": email_error,
                                "attempted_at": _now_iso(),
                            }
                        ),
                        invite_id,
                    ),
                )
                _record_activity_tx(
                    cur,
                    admin["company_id"],
                    "company_admin_invite_delivery_updated",
                    {
                        "company_admin_id": company_admin_id,
                        "company_admin_invite_id": invite_id,
                        "delivery_status": delivery_status,
                        "email_error": email_error,
                    },
                    actor_type="company_admin",
                    company_admin_id=company_admin_id,
                )

    return {"company": company, "admin": admin}


def update_company_admin(company_admin_id: str, request: CompanyAdminUpdateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            current = _fetch_company_admin_tx(cur, company_admin_id)
            next_full_name = request.full_name if request.full_name is not None else current["full_name"]
            next_job_title = request.job_title if request.job_title is not None else current["job_title"]
            next_access_level = request.access_level or current["access_level"]
            next_status = request.status or current["status"]
            active_owner_count = _count_active_owner_admins_tx(cur, current["company_id"])
            owner_would_stop_being_active = (
                current["access_level"] == "owner"
                and current["status"] == "active"
                and (next_access_level != "owner" or next_status != "active")
            )
            if owner_would_stop_being_active and active_owner_count <= 1:
                raise ValueError("At least one active owner must remain on the company account.")

            cur.execute(
                f"""
                UPDATE {_table_company_admins()}
                SET
                  full_name = %s,
                  access_level = %s,
                  job_title = %s,
                  status = %s
                WHERE company_admin_id = %s
                """,
                (
                    next_full_name,
                    next_access_level,
                    next_job_title,
                    next_status,
                    company_admin_id,
                ),
            )
            if next_status in {"revoked", "archived"}:
                _revoke_pending_company_admin_invites_tx(cur, company_admin_id, _now_iso())
                if current["status"] == "invited":
                    event_type = "company_admin_invite_revoked" if next_status == "revoked" else "company_admin_invite_archived"
                    _record_activity_tx(
                        cur,
                        current["company_id"],
                        event_type,
                        {
                            "company_admin_id": company_admin_id,
                            "email": current["email"],
                            "status": next_status,
                        },
                        actor_type="company_admin",
                        company_admin_id=company_admin_id,
                    )
            _record_activity_tx(
                cur,
                current["company_id"],
                "company_admin_updated",
                {
                    "company_admin_id": company_admin_id,
                    "access_level": next_access_level,
                    "status": next_status,
                },
                actor_type="company_admin",
                company_admin_id=company_admin_id,
            )
            return _fetch_company_admin_tx(cur, company_admin_id)


def create_training_group(company_id: str, request: TrainingGroupCreateRequest, request_context: dict[str, str | None]) -> dict[str, Any]:
    training_group_id = str(uuid4())
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company = _fetch_company_tx(cur, company_id)
            cur.execute(
                f"""
                INSERT INTO {_table_training_groups()} (
                  training_group_id,
                  company_id,
                  policy_case_id,
                  policy_document_id,
                  status,
                  title,
                  description,
                  course_version,
                  default_language,
                  planned_start_date,
                  planned_end_date,
                  metadata
                )
                VALUES (%s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    training_group_id,
                    company_id,
                    request.policy_case_id,
                    request.policy_document_id,
                    request.title,
                    request.description,
                    request.course_version,
                    request.default_language,
                    request.planned_start_date,
                    request.planned_end_date,
                    _jsonb({"request_context": request_context}),
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_created",
                {
                    "training_group_id": training_group_id,
                    "title": request.title,
                    "course_version": request.course_version,
                    "default_language": request.default_language,
                },
                actor_type="company_admin",
                training_group_id=training_group_id,
            )
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            return {"company": company, "training_group": training_group}


def load_training_group(company_id: str, training_group_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company = _fetch_company_tx(cur, company_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            policy_document = _resolve_group_policy_document_tx(cur, company, training_group)
            participants = _fetch_group_participants_tx(cur, training_group_id)
            progress = _build_training_group_progress_tx(cur, participants)
            exports = _resolve_group_bundle_exports(
                company,
                training_group,
                participants,
                _fetch_group_exports_tx(cur, training_group_id),
            )
            return {
                "company": company,
                "training_group": training_group,
                "policy_document": policy_document,
                "participants": participants,
                "progress": progress,
                "exports": exports,
            }


def update_training_group(company_id: str, training_group_id: str, request: TrainingGroupUpdateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            _fetch_company_tx(cur, company_id)
            current = _fetch_training_group_tx(cur, company_id, training_group_id)
            next_status = request.status or current["status"]
            next_title = request.title if request.title is not None else current["title"]
            next_description = request.description if request.description is not None else current["description"]
            next_start = request.planned_start_date if request.planned_start_date is not None else current["planned_start_date"]
            next_end = request.planned_end_date if request.planned_end_date is not None else current["planned_end_date"]
            launched_at = current["launched_at"]
            closed_at = current["closed_at"]
            now = _now_iso()
            if current["status"] != "in_progress" and next_status == "in_progress" and not launched_at:
                launched_at = now
            if next_status in {"completed", "archived", "cancelled"} and not closed_at:
                closed_at = now

            cur.execute(
                f"""
                UPDATE {_table_training_groups()}
                SET
                  status = %s,
                  title = %s,
                  description = %s,
                  planned_start_date = %s,
                  planned_end_date = %s,
                  launched_at = %s,
                  closed_at = %s
                WHERE company_id = %s
                  AND training_group_id = %s
                """,
                (
                    next_status,
                    next_title,
                    next_description,
                    next_start,
                    next_end,
                    launched_at,
                    closed_at,
                    company_id,
                    training_group_id,
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_updated",
                {
                    "training_group_id": training_group_id,
                    "status": next_status,
                    "title": next_title,
                },
                actor_type="company_admin",
                training_group_id=training_group_id,
            )
            return _fetch_training_group_tx(cur, company_id, training_group_id)


def _insert_company_participant_tx(
    cur,
    company_id: str,
    training_group_id: str,
    request: CompanyParticipantCreateRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    company_participant_id = str(uuid4())
    invite_token = _make_invite_token()
    invited_at = _now_iso()
    try:
        cur.execute(
            f"""
            INSERT INTO {_table_company_participants()} (
              company_participant_id,
              company_id,
              training_group_id,
              status,
              full_name,
              email,
              role,
              language,
              employee_reference,
              invite_token,
              invited_at,
              metadata
            )
            VALUES (%s, %s, %s, 'invited', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                company_participant_id,
                company_id,
                training_group_id,
                request.full_name,
                request.email,
                request.role,
                request.language,
                request.employee_reference,
                invite_token,
                invited_at,
                _jsonb({"request_context": request_context, "send_invite": request.send_invite}),
            ),
        )
    except UniqueViolation as exc:
        _raise_company_unique_conflict(exc, email=request.email)
    _record_activity_tx(
        cur,
        company_id,
        "company_participant_created",
        {
            "company_participant_id": company_participant_id,
            "email": request.email,
            "send_invite": request.send_invite,
        },
        actor_type="company_admin",
        training_group_id=training_group_id,
        company_participant_id=company_participant_id,
    )
    if request.send_invite:
        _record_activity_tx(
            cur,
            company_id,
            "company_participant_invite_requested",
            {
                "company_participant_id": company_participant_id,
                "email": request.email,
                "invite_token": invite_token,
            },
            actor_type="system",
            training_group_id=training_group_id,
            company_participant_id=company_participant_id,
        )
    return _fetch_company_participant_tx(cur, company_participant_id)


def create_company_participant(
    training_group_id: str,
    request: CompanyParticipantCreateRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    company: dict[str, Any] | None = None
    training_group: dict[str, Any] | None = None
    participant: dict[str, Any] | None = None
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT company_id FROM {_table_training_groups()} WHERE training_group_id = %s",
                (training_group_id,),
            )
            row = cur.fetchone()
            if not row:
                raise TrainingGroupNotFoundError(f"Training group not found: {training_group_id}")
            company_id = str(row["company_id"])
            company = _fetch_company_tx(cur, company_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            participant = _insert_company_participant_tx(cur, company_id, training_group_id, request, request_context)
            _refresh_training_group_counts_tx(cur, training_group_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
    if request.send_invite and company and training_group and participant:
        participant = _deliver_company_participant_invite(company, training_group, participant)
    return {"training_group": training_group, "participant": participant}


def import_company_participants(
    training_group_id: str,
    request: TrainingGroupParticipantsImportRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    company: dict[str, Any] | None = None
    training_group: dict[str, Any] | None = None
    inserted: list[dict[str, Any]] = []
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT company_id FROM {_table_training_groups()} WHERE training_group_id = %s",
                (training_group_id,),
            )
            row = cur.fetchone()
            if not row:
                raise TrainingGroupNotFoundError(f"Training group not found: {training_group_id}")
            company_id = str(row["company_id"])
            company = _fetch_company_tx(cur, company_id)
            for item in request.participants:
                participant_request = item.model_copy(update={"send_invite": request.send_invites})
                inserted.append(_insert_company_participant_tx(cur, company_id, training_group_id, participant_request, request_context))
            _refresh_training_group_counts_tx(cur, training_group_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            _record_activity_tx(
                cur,
                company_id,
                "training_group_participants_imported",
                {
                    "training_group_id": training_group_id,
                    "participants_count": len(inserted),
                    "send_invites": request.send_invites,
                },
                actor_type="company_admin",
                training_group_id=training_group_id,
            )
    if request.send_invites and company and training_group:
        inserted = [_deliver_company_participant_invite(company, training_group, participant) for participant in inserted]
    return {"training_group": training_group, "participants": inserted}


def update_company_participant(company_participant_id: str, request: CompanyParticipantUpdateRequest) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            current = _fetch_company_participant_tx(cur, company_participant_id)
            if request.status in {"completed", "certificate_issued"}:
                raise ValueError("Completed and issued-certificate states are managed automatically by the course.")
            next_full_name = request.full_name if request.full_name is not None else current["full_name"]
            next_email = request.email if request.email is not None else current["email"]
            next_status = request.status or current["status"]
            next_role = request.role if request.role is not None else current["role"]
            next_language = request.language or current["language"]
            next_invite_token = current["invite_token"]
            next_employee_reference = (
                request.employee_reference if request.employee_reference is not None else current["employee_reference"]
            )
            if next_email != current["email"]:
                next_invite_token = _make_invite_token()
            try:
                cur.execute(
                    f"""
                    UPDATE {_table_company_participants()}
                    SET
                      full_name = %s,
                      email = %s,
                      status = %s,
                      role = %s,
                      language = %s,
                      employee_reference = %s,
                      invite_token = %s
                    WHERE company_participant_id = %s
                    """,
                    (
                        next_full_name,
                        next_email,
                        next_status,
                        next_role,
                        next_language,
                        next_employee_reference,
                        next_invite_token,
                        company_participant_id,
                    ),
                )
            except UniqueViolation as exc:
                _raise_company_unique_conflict(exc, email=next_email)
            _refresh_training_group_counts_tx(cur, current["training_group_id"])
            _record_activity_tx(
                cur,
                current["company_id"],
                "company_participant_updated",
                {
                    "company_participant_id": company_participant_id,
                    "email": next_email,
                    "status": next_status,
                    "invite_token_rotated": next_invite_token != current["invite_token"],
                },
                actor_type="company_admin",
                training_group_id=current["training_group_id"],
                company_participant_id=company_participant_id,
                course_enrollment_id=current["course_enrollment_id"],
            )
            return _fetch_company_participant_tx(cur, company_participant_id)


def resend_company_participant_invite(company_participant_id: str) -> dict[str, Any]:
    company: dict[str, Any] | None = None
    training_group: dict[str, Any] | None = None
    participant: dict[str, Any] | None = None
    with connect_dict() as conn:
        with conn.cursor() as cur:
            participant = _fetch_company_participant_tx(cur, company_participant_id)
            if participant["status"] == "cancelled":
                raise ValueError("Cancelled participants cannot receive a new invitation.")
            company = _fetch_company_tx(cur, participant["company_id"])
            training_group = _fetch_training_group_tx(cur, participant["company_id"], participant["training_group_id"])
    if company and training_group and participant:
        return _deliver_company_participant_invite(company, training_group, participant)
    raise CompanyParticipantNotFoundError(f"Company participant not found: {company_participant_id}")


def load_company_participant_invite(invite_token: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            participant = _fetch_company_participant_by_invite_token_tx(cur, invite_token)
            company = _fetch_company_tx(cur, participant["company_id"])
            training_group = _fetch_training_group_tx(cur, participant["company_id"], participant["training_group_id"])
            return {
                "company": company,
                "training_group": training_group,
                "participant": participant,
            }


def accept_company_participant_invite(
    invite_token: str,
    request: CompanyParticipantInviteAcceptRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            participant = _fetch_company_participant_by_invite_token_tx(cur, invite_token)
            if participant["status"] in {"cancelled", "bounced"}:
                raise ValueError(f"Invite cannot be accepted from status: {participant['status']}")

            next_status = "opened" if participant["status"] == "invited" else participant["status"]
            now = _now_iso()
            opened_at = participant["opened_at"] or now

            cur.execute(
                f"""
                UPDATE {_table_company_participants()}
                SET
                  status = %s,
                  opened_at = %s,
                  last_seen_at = %s,
                  metadata = jsonb_set(
                    COALESCE(metadata, '{{}}'::jsonb),
                    '{{invite_acceptance}}',
                    %s
                  )
                WHERE company_participant_id = %s
                """,
                (
                    next_status,
                    opened_at,
                    now,
                    _jsonb(
                        {
                            "accepted_at": now,
                            "page_url": request.page_url,
                            "request_context": request_context,
                        }
                    ),
                    participant["company_participant_id"],
                ),
            )
            _record_activity_tx(
                cur,
                participant["company_id"],
                "company_participant_invite_accepted",
                {
                    "company_participant_id": participant["company_participant_id"],
                    "invite_token": invite_token,
                    "page_url": request.page_url,
                },
                actor_type="participant",
                training_group_id=participant["training_group_id"],
                company_participant_id=participant["company_participant_id"],
                course_enrollment_id=participant["course_enrollment_id"],
            )
            participant = _fetch_company_participant_by_invite_token_tx(cur, invite_token)
            company = _fetch_company_tx(cur, participant["company_id"])
            training_group = _fetch_training_group_tx(cur, participant["company_id"], participant["training_group_id"])
            return {
                "company": company,
                "training_group": training_group,
                "participant": participant,
            }


def _build_participants_csv_bytes(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
) -> bytes:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "company_legal_name",
            "training_group_title",
            "company_participant_id",
            "employee_reference",
            "full_name",
            "email",
            "role",
            "language",
            "status",
            "invited_at",
            "opened_at",
            "started_at",
            "completed_at",
            "certificate_issued_at",
            "course_enrollment_id",
            "enrollment_origin",
            "invite_delivery_status",
            "certificate_code",
            "certificate_verify_url",
        ]
    )
    for participant in participants:
        artifact = participant.get("certificate_artifact") or {}
        writer.writerow(
            [
                company["legal_name"],
                training_group["title"],
                participant["company_participant_id"],
                participant.get("employee_reference") or "",
                participant["full_name"],
                participant["email"],
                participant.get("role") or "",
                participant["language"],
                participant["status"],
                participant.get("invited_at") or "",
                participant.get("opened_at") or "",
                participant.get("started_at") or "",
                participant.get("completed_at") or "",
                participant.get("certificate_issued_at") or "",
                participant.get("course_enrollment_id") or "",
                participant.get("enrollment_origin") or "",
                participant.get("invite_delivery_status") or "",
                artifact.get("verification_code") or "",
                artifact.get("verification_url") or "",
            ]
        )
    return output.getvalue().encode("utf-8")


def _build_completion_report_bytes(
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
) -> bytes:
    issued = [item for item in participants if item["status"] == "certificate_issued"]
    completed = [item for item in participants if item["status"] in {"completed", "certificate_issued"}]
    styles = _group_report_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"HREVN Start · Informe de grupo · {training_group['title']}",
        author="HREVN",
    )

    summary_rows = [
        ("Empresa", company.get("display_name") or company["legal_name"]),
        ("Grupo", training_group["title"]),
        ("Estado del grupo", training_group["status"]),
        ("Versión del curso", training_group["course_version"]),
        ("Idioma por defecto", training_group["default_language"]),
        ("Participantes", str(len(participants))),
        ("Completados", str(len(completed))),
        ("Certificados emitidos", str(len(issued))),
        ("Inicio previsto", _format_display_date(training_group.get("planned_start_date"))),
        ("Fin previsto", _format_display_date(training_group.get("planned_end_date"))),
    ]

    story = [
        Paragraph("HREVN START · INFORME DE GRUPO", styles["eyebrow"]),
        Paragraph("Informe de finalización y trazabilidad básica", styles["title"]),
        Paragraph(
            (
                "Documento de resumen para empresa con estado del grupo, participantes, certificados emitidos "
                "y trazabilidad mínima del recorrido."
            ),
            styles["lead"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("Resumen del grupo", styles["section"]),
        _group_summary_table(summary_rows, styles),
        Spacer(1, 6 * mm),
        Paragraph("Participantes y situación actual", styles["section"]),
        _participants_report_table(participants, styles),
        Spacer(1, 5 * mm),
        Paragraph(
            (
                "Este informe forma parte del paquete documental de HREVN Start. Resume el estado del grupo y "
                "puede acompañarse del CSV de participantes y de los certificados emitidos en PDF."
            ),
            styles["note"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()


def _write_certificates_zip(
    target_path: Path,
    participants: list[dict[str, Any]],
) -> None:
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        added = 0
        for participant in participants:
            enrollment_id = participant.get("course_enrollment_id")
            artifact = participant.get("certificate_artifact") or {}
            if not enrollment_id or not artifact.get("artifact_id"):
                continue
            path, filename = resolve_course_certificate_download(enrollment_id)
            safe_name = f"{_slugify_filename(participant['full_name'])}-{filename}"
            bundle.write(path, arcname=safe_name)
            added += 1
        if added == 0:
            bundle.writestr(
                "README.txt",
                "No issued course certificates were available for this training group when the export was generated.\n",
            )


def _write_evidence_bundle_zip(
    target_path: Path,
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
) -> None:
    base_slug = _slugify_filename(f"{company['legal_name']}-{training_group['title']}")
    report_name = f"hrevn-start-informe-grupo-{base_slug}.pdf"
    csv_name = f"hrevn-start-participantes-{base_slug}.csv"

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(report_name, _build_completion_report_bytes(company, training_group, participants))
        bundle.writestr(csv_name, _build_participants_csv_bytes(company, training_group, participants))

        added_certificates = 0
        for participant in participants:
            enrollment_id = participant.get("course_enrollment_id")
            artifact = participant.get("certificate_artifact") or {}
            if not enrollment_id or not artifact.get("artifact_id"):
                continue
            path, filename = resolve_course_certificate_download(enrollment_id)
            safe_name = f"certificados/{_slugify_filename(participant['full_name'])}-{filename}"
            bundle.write(path, arcname=safe_name)
            added_certificates += 1

        if added_certificates == 0:
            bundle.writestr(
                "certificados/README.txt",
                "Todavía no había certificados emitidos en el momento de generar este paquete.\n",
            )


def _generate_training_group_export_file(
    export: dict[str, Any],
    company: dict[str, Any],
    training_group: dict[str, Any],
    participants: list[dict[str, Any]],
) -> tuple[str, str, str]:
    base_slug = _slugify_filename(f"{company['legal_name']}-{training_group['title']}")
    if export["export_kind"] == "participants_csv":
        file_name = f"hrevn-start-participants-{base_slug}.csv"
        relative_path = f"company-exports/{export['training_group_export_id']}-{file_name}"
        target_path = settings.course_storage_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(_build_participants_csv_bytes(company, training_group, participants))
    elif export["export_kind"] == "certificates_zip":
        file_name = f"hrevn-start-certificates-{base_slug}.zip"
        relative_path = f"company-exports/{export['training_group_export_id']}-{file_name}"
        target_path = settings.course_storage_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _write_certificates_zip(target_path, participants)
    elif export["export_kind"] == "completion_report":
        file_name = f"hrevn-start-completion-report-{base_slug}.pdf"
        relative_path = f"company-exports/{export['training_group_export_id']}-{file_name}"
        target_path = settings.course_storage_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(_build_completion_report_bytes(company, training_group, participants))
    elif export["export_kind"] == "evidence_bundle":
        file_name = f"hrevn-start-evidence-bundle-{base_slug}.zip"
        relative_path = f"company-exports/{export['training_group_export_id']}-{file_name}"
        target_path = settings.course_storage_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _write_evidence_bundle_zip(target_path, company, training_group, participants)
    else:
        raise ValueError(f"Export kind not implemented yet: {export['export_kind']}")
    return file_name, relative_path, _sha256_file(target_path)


def _mark_training_group_export_generated(
    training_group_export_id: str,
    *,
    company_id: str,
    training_group_id: str,
    export_kind: str,
    file_name: str,
    relative_path: str,
    file_hash: str,
    participants_count: int,
) -> dict[str, Any]:
    generated_at = _now_iso()
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_table_exports()}
                SET
                  status = 'generated',
                  file_name = %s,
                  storage_path = %s,
                  sha256 = %s,
                  generated_at = %s,
                  metadata = COALESCE(metadata, '{{}}'::jsonb) || %s
                WHERE training_group_export_id = %s
                """,
                (
                    file_name,
                    relative_path,
                    file_hash,
                    generated_at,
                    _jsonb(
                        {
                            "participants_count": participants_count,
                            "download_url": _export_download_path(training_group_export_id),
                        }
                    ),
                    training_group_export_id,
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_export_generated",
                {
                    "training_group_export_id": training_group_export_id,
                    "training_group_id": training_group_id,
                    "export_kind": export_kind,
                    "file_name": file_name,
                    "relative_path": relative_path,
                    "sha256": file_hash,
                },
                actor_type="system",
                training_group_id=training_group_id,
            )
            return _fetch_export_tx(cur, training_group_export_id)


def _mark_training_group_export_failed(
    training_group_export_id: str,
    *,
    company_id: str,
    training_group_id: str,
    export_kind: str,
    error_message: str,
) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_table_exports()}
                SET
                  status = 'failed',
                  metadata = COALESCE(metadata, '{{}}'::jsonb) || %s
                WHERE training_group_export_id = %s
                """,
                (
                    _jsonb({"generation_error": error_message, "failed_at": _now_iso()}),
                    training_group_export_id,
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_export_failed",
                {
                    "training_group_export_id": training_group_export_id,
                    "training_group_id": training_group_id,
                    "export_kind": export_kind,
                    "error_message": error_message,
                },
                actor_type="system",
                training_group_id=training_group_id,
            )
            return _fetch_export_tx(cur, training_group_export_id)


def _regenerate_training_group_export_file(
    training_group_export_id: str,
    export: dict[str, Any],
) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            company_id = str(export["company_id"])
            training_group_id = str(export["training_group_id"])
            company = _fetch_company_tx(cur, company_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            participants = _fetch_group_participants_tx(cur, training_group_id)
        file_name, relative_path, file_hash = _generate_training_group_export_file(
            export,
            company,
            training_group,
            participants,
        )
        with conn.cursor() as cur:
            generated_at = _now_iso()
            cur.execute(
                f"""
                UPDATE {_table_exports()}
                SET
                  status = 'generated',
                  file_name = %s,
                  storage_path = %s,
                  sha256 = %s,
                  generated_at = COALESCE(generated_at, %s),
                  metadata = COALESCE(metadata, '{{}}'::jsonb) || %s
                WHERE training_group_export_id = %s
                """,
                (
                    file_name,
                    relative_path,
                    file_hash,
                    generated_at,
                    _jsonb(
                        {
                            "participants_count": len(participants),
                            "download_url": _export_download_path(training_group_export_id),
                            "regenerated_at": generated_at,
                        }
                    ),
                    training_group_export_id,
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_export_regenerated",
                {
                    "training_group_export_id": training_group_export_id,
                    "training_group_id": training_group_id,
                    "export_kind": export["export_kind"],
                    "file_name": file_name,
                    "relative_path": relative_path,
                    "sha256": file_hash,
                },
                actor_type="system",
                training_group_id=training_group_id,
            )
            return _fetch_export_tx(cur, training_group_export_id)


def create_training_group_export(
    training_group_id: str,
    request: TrainingGroupExportCreateRequest,
    request_context: dict[str, str | None],
) -> dict[str, Any]:
    export_id = str(uuid4())
    company: dict[str, Any] | None = None
    training_group: dict[str, Any] | None = None
    participants: list[dict[str, Any]] = []
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT company_id FROM {_table_training_groups()} WHERE training_group_id = %s",
                (training_group_id,),
            )
            row = cur.fetchone()
            if not row:
                raise TrainingGroupNotFoundError(f"Training group not found: {training_group_id}")
            company_id = str(row["company_id"])
            company = _fetch_company_tx(cur, company_id)
            training_group = _fetch_training_group_tx(cur, company_id, training_group_id)
            participants = _fetch_group_participants_tx(cur, training_group_id)
            cur.execute(
                f"""
                INSERT INTO {_table_exports()} (
                  training_group_export_id,
                  company_id,
                  training_group_id,
                  export_kind,
                  status,
                  metadata
                )
                VALUES (%s, %s, %s, %s, 'queued', %s)
                """,
                (
                    export_id,
                    company_id,
                    training_group_id,
                    request.export_kind,
                    _jsonb({"request_context": request_context}),
                ),
            )
            _record_activity_tx(
                cur,
                company_id,
                "training_group_export_requested",
                {
                    "training_group_export_id": export_id,
                    "training_group_id": training_group_id,
                    "export_kind": request.export_kind,
                },
                actor_type="company_admin",
                training_group_id=training_group_id,
            )
            export = _fetch_export_tx(cur, export_id)
    bundle_ready, bundle_message = _training_group_bundle_gate(training_group, participants)
    if request.export_kind == "evidence_bundle" and not bundle_ready:
        with connect_dict() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_table_exports()}
                    SET
                      status = 'queued',
                      metadata = COALESCE(metadata, '{{}}'::jsonb) || %s
                    WHERE training_group_export_id = %s
                    """,
                    (
                        _jsonb(
                            {
                                "availability_rule": "all_completed_or_30_days",
                                "availability_message": bundle_message,
                            }
                        ),
                        export_id,
                    ),
                )
                export = _fetch_export_tx(cur, export_id)
        return {"training_group": training_group, "export": export}

    try:
        assert company is not None
        assert training_group is not None
        file_name, relative_path, file_hash = _generate_training_group_export_file(
            export,
            company,
            training_group,
            participants,
        )
        export = _mark_training_group_export_generated(
            export_id,
            company_id=company["company_id"],
            training_group_id=training_group_id,
            export_kind=request.export_kind,
            file_name=file_name,
            relative_path=relative_path,
            file_hash=file_hash,
            participants_count=len(participants),
        )
    except Exception as exc:
        export = _mark_training_group_export_failed(
            export_id,
            company_id=company["company_id"] if company else company_id,
            training_group_id=training_group_id,
            export_kind=request.export_kind,
            error_message=str(exc),
        )
    return {"training_group": training_group, "export": export}


def resolve_training_group_export_download(training_group_export_id: str) -> tuple[Path, str, str]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            export = _fetch_export_tx(cur, training_group_export_id)
            if not export:
                raise TrainingGroupExportNotFoundError(
                    f"Training group export not found: {training_group_export_id}"
                )
            if export["status"] != "generated" or not export["storage_path"] or not export["file_name"]:
                raise TrainingGroupExportNotReadyError(
                    f"Training group export is not ready for download: {training_group_export_id}"
                )
            path = settings.course_storage_dir / export["storage_path"]
            if not path.exists():
                export = _regenerate_training_group_export_file(training_group_export_id, export)
                path = settings.course_storage_dir / export["storage_path"]
                if not path.exists():
                    raise TrainingGroupExportNotReadyError(
                        f"Training group export file is missing: {training_group_export_id}"
                    )
            media_type = "application/octet-stream"
            if path.suffix == ".csv":
                media_type = "text/csv"
            elif path.suffix == ".zip":
                media_type = "application/zip"
            elif path.suffix == ".txt":
                media_type = "text/plain"
            return path, export["file_name"], media_type


def resolve_training_group_export_company_id(training_group_export_id: str) -> str:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            export = _fetch_export_tx(cur, training_group_export_id)
            if not export:
                raise TrainingGroupExportNotFoundError(
                    f"Training group export not found: {training_group_export_id}"
                )
            return str(export["company_id"])
