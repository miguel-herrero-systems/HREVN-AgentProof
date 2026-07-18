from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
import json
from pathlib import Path
import smtplib
from typing import Any
from uuid import uuid4

from ..config import settings
from ..models.requests import ContactRequest, LeadCaptureRequest


@dataclass(frozen=True)
class LeadSubmissionResult:
    submission_id: str
    delivery_status: str
    email_error: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def leads_dir() -> Path:
    settings.lead_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.lead_storage_dir


def _submission_payload(request: LeadCaptureRequest) -> dict[str, Any]:
    return {
        "submission_id": f"lead-{uuid4().hex[:12]}",
        "submitted_at": _now_iso(),
        "email": request.email,
        "source_page": request.source_page,
        "language": request.language,
        "subject": request.subject,
        "product_interest": request.product_interest,
        "result_level": request.result_level,
        "result_eligibility": request.result_eligibility,
        "result_eligibility_reasons": request.result_eligibility_reasons,
        "result_primary_use": request.result_primary_use,
        "result_signals": request.result_signals,
        "answers": request.answers,
        "page_url": request.page_url,
        "user_agent": request.user_agent,
    }


def _contact_payload(request: ContactRequest) -> dict[str, Any]:
    return {
        "submission_id": f"contact-{uuid4().hex[:12]}",
        "submitted_at": _now_iso(),
        "name": request.name,
        "email": request.email,
        "organization": request.organization,
        "source_page": request.source_page,
        "language": request.language,
        "subject": request.subject,
        "product_interest": request.product_interest,
        "landing": request.landing,
        "profile_type": request.profile_type,
        "ai_system_type": request.ai_system_type,
        "current_situation": request.current_situation,
        "objective": request.objective,
        "message": request.message,
        "contact_consent": request.contact_consent,
        "page_url": request.page_url,
        "user_agent": request.user_agent,
    }


def store_lead_submission(payload: dict[str, Any]) -> Path:
    day_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    target = leads_dir() / f"ai_use_check_leads_{day_stamp}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def store_contact_submission(payload: dict[str, Any]) -> Path:
    day_stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    target = leads_dir() / f"contact_requests_{day_stamp}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return target


def _format_answers(answers: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in sorted(answers):
        value = answers[key]
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) if value else "-"
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines) if lines else "- (sin respuestas registradas)"


def _format_bullets(items: list[str] | tuple[str, ...] | None, empty_text: str) -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in items if str(item).strip()) or f"- {empty_text}"


def _compact_value(value: Any, empty_text: str = "-") -> str:
    if value is None:
        return empty_text
    text = str(value).strip()
    return text or empty_text


def build_lead_email(payload: dict[str, Any]) -> EmailMessage:
    subject = payload.get("subject") or "Nuevo lead HREVN"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.lead_email_sender
    message["To"] = settings.lead_email_recipient
    if settings.lead_email_cc:
        message["Cc"] = ", ".join(settings.lead_email_cc)
    message["Reply-To"] = payload["email"]

    reasons_text = _format_bullets(
        payload.get("result_eligibility_reasons"),
        "Sin razones adicionales.",
    )
    signals_text = _format_bullets(
        payload.get("result_signals"),
        "Sin señales adicionales.",
    )

    body = f"""Nuevo lead desde HREVN AI Use Check

Resumen
- Submission ID: {payload['submission_id']}
- Submitted at: {payload['submitted_at']}
- Source page: {_compact_value(payload.get('source_page'))}
- Language: {_compact_value(payload.get('language'))}
- Visitor email: {_compact_value(payload.get('email'))}
- Page URL: {_compact_value(payload.get('page_url'))}

Resultado
- Exposure level: {_compact_value(payload.get('result_level'))}
- Training eligibility: {_compact_value(payload.get('result_eligibility'))}
- Primary use: {_compact_value(payload.get('result_primary_use'))}

Razones de elegibilidad
{reasons_text}

Señales detectadas
{signals_text}

Respuestas
{_format_answers(payload.get('answers') or {})}

Trazabilidad técnica
- User agent: {_compact_value(payload.get('user_agent'))}
"""
    message.set_content(body)
    return message


def build_contact_email(payload: dict[str, Any]) -> EmailMessage:
    subject = payload.get("subject") or "New HREVN contact request"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.lead_email_sender
    message["To"] = settings.lead_email_recipient
    if settings.lead_email_cc:
        message["Cc"] = ", ".join(settings.lead_email_cc)
    message["Reply-To"] = payload["email"]

    body = f"""New HREVN contact request

Summary
- Submission ID: {payload['submission_id']}
- Submitted at: {payload['submitted_at']}
- Source page: {_compact_value(payload.get('source_page'))}
- Language: {_compact_value(payload.get('language'))}
- Page URL: {_compact_value(payload.get('page_url'))}

Contact
- Name: {_compact_value(payload.get('name'))}
- Email: {_compact_value(payload.get('email'))}
- Organization: {_compact_value(payload.get('organization'))}

Qualification
- Product interest: {_compact_value(payload.get('product_interest'))}
- Landing: {_compact_value(payload.get('landing'))}
- Profile type: {_compact_value(payload.get('profile_type'))}
- AI system type: {_compact_value(payload.get('ai_system_type'))}
- Current situation: {_compact_value(payload.get('current_situation'))}
- Objective: {_compact_value(payload.get('objective'))}
- Contact consent: {_compact_value(payload.get('contact_consent'))}

Message
{_compact_value(payload.get('message'))}

Technical trace
- User agent: {_compact_value(payload.get('user_agent'))}
"""
    message.set_content(body)
    return message


def send_lead_email(payload: dict[str, Any]) -> None:
    if not settings.lead_smtp_host:
        raise RuntimeError("SMTP host not configured.")

    message = build_lead_email(payload)
    recipients = [settings.lead_email_recipient, *settings.lead_email_cc]

    if settings.lead_smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
            if settings.lead_smtp_username:
                smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
            smtp.send_message(message, to_addrs=recipients)
        return

    with smtplib.SMTP(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
        if settings.lead_smtp_use_tls:
            smtp.starttls()
        if settings.lead_smtp_username:
            smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
        smtp.send_message(message, to_addrs=recipients)


def send_contact_email(payload: dict[str, Any]) -> None:
    if not settings.lead_smtp_host:
        raise RuntimeError("SMTP host not configured.")

    message = build_contact_email(payload)
    recipients = [settings.lead_email_recipient, *settings.lead_email_cc]

    if settings.lead_smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
            if settings.lead_smtp_username:
                smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
            smtp.send_message(message, to_addrs=recipients)
        return

    with smtplib.SMTP(settings.lead_smtp_host, settings.lead_smtp_port, timeout=30) as smtp:
        if settings.lead_smtp_use_tls:
            smtp.starttls()
        if settings.lead_smtp_username:
            smtp.login(settings.lead_smtp_username, settings.lead_smtp_password)
        smtp.send_message(message, to_addrs=recipients)


def validate_lead_origin(origin: str | None) -> None:
    if not origin:
        return
    if origin not in settings.lead_allowed_origins:
        raise ValueError(f"Origin not allowed: {origin}")


def capture_lead_submission(request: LeadCaptureRequest) -> LeadSubmissionResult:
    payload = _submission_payload(request)
    store_lead_submission(payload)

    try:
        send_lead_email(payload)
    except Exception as exc:
        return LeadSubmissionResult(
            submission_id=payload["submission_id"],
            delivery_status="stored_only",
            email_error=str(exc),
        )

    return LeadSubmissionResult(
        submission_id=payload["submission_id"],
        delivery_status="emailed",
        email_error=None,
    )


def capture_contact_submission(request: ContactRequest) -> LeadSubmissionResult:
    payload = _contact_payload(request)
    store_contact_submission(payload)

    try:
        send_contact_email(payload)
    except Exception as exc:
        return LeadSubmissionResult(
            submission_id=payload["submission_id"],
            delivery_status="stored_only",
            email_error=str(exc),
        )

    return LeadSubmissionResult(
        submission_id=payload["submission_id"],
        delivery_status="emailed",
        email_error=None,
    )
