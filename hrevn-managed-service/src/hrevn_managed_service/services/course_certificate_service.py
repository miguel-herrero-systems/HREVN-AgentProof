from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

from ..config import settings
from .course_service import (
    CourseCompletionBlockedError,
    CourseEnrollmentNotFoundError,
    _build_review_recommendation,
    _ensure_certificate_artifact,
    _fetch_course_tx,
    _jsonb,
    _record_activity_tx,
    _sync_company_participant_from_enrollment_tx,
    _table_enrollments,
)
from .db import connect_dict
from .hrevn_start_anchor_service import anchor_course_artifact, build_course_anchor_payload


PROGRAM_TITLE = {
    "es": "HREVN Start · Alfabetización básica en IA",
    "en": "HREVN Start · Basic AI literacy",
}

ACCREDITATION_STATEMENT = {
    "es": (
        "Este certificado acredita la realización completada de la formación básica en uso responsable de "
        "inteligencia artificial dentro del recorrido HREVN Start."
    ),
    "en": (
        "This certificate records the completed basic training in the responsible use of artificial intelligence "
        "within the HREVN Start path."
    ),
}

PASS_RULE = {
    "es": "Superación de los 5 bloques obligatorios con un mínimo de 4 respuestas correctas sobre 5 en cada bloque.",
    "en": "Successful completion of the 5 required blocks with a minimum of 4 correct answers out of 5 in each block.",
}

IDENTITY_NOTE = {
    "es": "La persona participante confirmó expresamente que era la destinataria de esta invitación antes de iniciar el curso.",
    "en": "The participant explicitly confirmed they were the intended recipient of this invitation before starting the course.",
}

LEGAL_NOTICE = {
    "es": (
        "Este certificado acredita la realización y superación del curso mediante una inscripción individual asociada "
        "al correo electrónico declarado para la persona participante. No constituye por sí solo una verificación "
        "presencial o documental de identidad, ni una garantía absoluta de cumplimiento normativo."
    ),
    "en": (
        "This certificate records the completion and successful passing of the course through an individual enrollment "
        "associated with the email address declared for the participant. By itself, it does not constitute in-person "
        "or documentary identity verification, nor an absolute guarantee of regulatory compliance."
    ),
}

NON_ACCREDITATION_NOTE = {
    "es": "Este certificado acredita formación completada. No certifica cumplimiento normativo ni sustituye asesoramiento profesional.",
    "en": "This certificate records completed training. It does not certify regulatory compliance or replace professional advice.",
}

REVIEW_NOTE_PREFIX = {
    "es": "Recomendación de repaso",
    "en": "Review recommendation",
}

BLOCK_TITLES = {
    "es": {
        "block_1": "Qué es y qué no es usar IA en empresa",
        "block_2": "Herramientas, datos y límites básicos",
        "block_3": "Revisión humana y uso responsable",
        "block_4": "Política interna inicial y responsabilidades",
        "block_5": "Evidencia mínima y siguiente paso razonable",
        "block_6": "Chatbot ligero, transparencia y derivación humana",
    },
    "en": {
        "block_1": "What using AI in a company is and is not",
        "block_2": "Tools, data and basic limits",
        "block_3": "Human review and responsible use",
        "block_4": "Initial internal policy and responsibilities",
        "block_5": "Minimum evidence and the next reasonable step",
        "block_6": "Light chatbot, transparency and human handoff",
    },
}


class CourseCertificateError(RuntimeError):
    error_code = "course_certificate_error"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _certificates_dir() -> Path:
    target = settings.course_storage_dir / "certificates"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _certificate_file_path(artifact_id: str, language: str) -> Path:
    suffix = "es" if language == "es" else "en"
    return _certificates_dir() / f"{artifact_id}_{suffix}.pdf"


def _slugify_filename(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "participant"


def _verification_record_is_final() -> bool:
    return settings.public_site_base_url.rstrip("/") == "https://hrevn.com"


def _format_display_date(value: str | None, language: str) -> str:
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
    if language == "es":
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
    months = {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    }
    return f"{months[date.month]} {date.day}, {date.year}"


def _mask_email(value: str) -> str:
    if "@" not in value:
        return value
    local_part, domain = value.split("@", 1)
    if len(local_part) <= 3:
        visible = local_part[:1]
    else:
        visible = local_part[: min(3, max(1, len(local_part) // 2))]
    return f"{visible}***@{domain}"


def _build_styles():
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
            fontSize=25,
            leading=29,
            textColor=colors.HexColor("#241b18"),
            spaceAfter=10,
        ),
        "lead": ParagraphStyle(
            "Lead",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11.5,
            leading=17,
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
            fontSize=9.3,
            leading=13,
            textColor=colors.HexColor("#6d6059"),
            spaceAfter=6,
        ),
        "proof_code": ParagraphStyle(
            "ProofCode",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=21,
            leading=24,
            textColor=colors.HexColor("#241b18"),
            spaceAfter=4,
        ),
        "proof_label": ParagraphStyle(
            "ProofLabel",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.4,
            leading=11.5,
            textColor=colors.HexColor("#8a7566"),
            spaceAfter=4,
        ),
    }


def _summary_table(rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    body = [[Paragraph(f"<b>{label}</b>", styles["body"]), Paragraph(value, styles["body"])] for label, value in rows]
    table = Table(body, colWidths=[48 * mm, 112 * mm])
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


def _record_table(rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    body = [[Paragraph(label, styles["proof_label"]), Paragraph(value, styles["body"])] for label, value in rows]
    table = Table(body, colWidths=[46 * mm, 114 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdfa")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#e5d2c0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#efe3d7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _proof_band(
    verification_code: str,
    verification_url: str,
    language: str,
    styles: dict[str, ParagraphStyle],
) -> Table:
    widget = qr.QrCodeWidget(verification_url)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    size = 31 * mm
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    label = "Registro verificable" if language == "es" else "Verifiable record"
    body = [
        [
            Paragraph(label, styles["proof_label"]),
            "",
        ],
        [
            Paragraph(verification_code, styles["proof_code"]),
            drawing,
        ],
        [
            Paragraph(
                "Código único emitido por HREVN para este certificado."
                if language == "es"
                else "Unique code issued by HREVN for this certificate.",
                styles["body"],
            ),
            Paragraph(
                "Escanea para abrir la verificación."
                if language == "es"
                else "Scan to open verification.",
                styles["note"],
            ),
        ],
    ]
    table = Table(body, colWidths=[111 * mm, 46 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff9f2")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#e5d2c0")),
                ("SPAN", (0, 0), (1, 0)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 1), (1, 1), "RIGHT"),
                ("ALIGN", (1, 2), (1, 2), "RIGHT"),
            ]
        )
    )
    return table


def _verification_qr_block(url: str, language: str, styles: dict[str, ParagraphStyle]) -> Table:
    widget = qr.QrCodeWidget(url)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    size = 34 * mm
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    label = (
        "Escanea este código para abrir el registro verificable del certificado."
        if language == "es" and _verification_record_is_final()
        else "Escanea este código para abrir el registro de verificación previsto del certificado."
        if language == "es"
        else "Scan this code to open the planned certificate verification record."
    )
    table = Table(
        [[drawing, Paragraph(label, styles["body"])]],
        colWidths=[40 * mm, 120 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _anchor_network_label(network: str | None, language: str) -> str:
    labels = {
        "sepolia": "Ethereum Sepolia",
        "base-sepolia": "Base Sepolia",
        "base": "Base",
    }
    if not network:
        return "—"
    return labels.get(network, network)


def _anchor_status_label(status: str | None, language: str) -> str:
    labels_es = {
        "anchored": "Anclado",
        "anchor_pending": "Pendiente",
        "anchor_failed": "Incidencia temporal",
    }
    labels_en = {
        "anchored": "Anchored",
        "anchor_pending": "Pending",
        "anchor_failed": "Temporary issue",
    }
    if not status:
        return "—"
    return (labels_es if language == "es" else labels_en).get(status, status)


def _short_transaction_reference(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 18:
        return value
    return f"{value[:10]}...{value[-6:]}"


def _block_labels(language: str, block_codes: list[str]) -> str:
    titles = [BLOCK_TITLES[language].get(code, code) for code in block_codes]
    return ", ".join(titles)


def _review_paragraph(language: str, recommendation: dict[str, Any]) -> str | None:
    if not recommendation.get("recommended"):
        return None
    titles = _block_labels(language, recommendation.get("blocks", []))
    if language == "es":
        return (
            f"{REVIEW_NOTE_PREFIX['es']}: se recomienda revisar nuevamente {titles} como medida interna de refuerzo "
            "antes de utilizar herramientas de IA en tareas sensibles o con impacto relevante. "
            "Esta recomendación no invalida la superación del curso."
        )
    return (
        f"{REVIEW_NOTE_PREFIX['en']}: it is advisable to revisit {titles} as an internal reinforcement measure "
        "before using AI tools in sensitive or higher-impact tasks. "
        "This recommendation does not invalidate course completion."
    )


def _build_certificate_pdf(course: dict[str, Any], artifact: dict[str, Any], target_path: Path) -> None:
    language = course["language"]
    styles = _build_styles()
    paper = colors.HexColor("#f8f1e8")
    brand = colors.HexColor("#b7633b")
    line = colors.HexColor("#ddc8b5")
    muted = colors.HexColor("#7a6a60")
    summary_rows = [
        ("Participante" if language == "es" else "Participant", course["full_name"]),
        ("Email", course["email"]),
        ("Empresa" if language == "es" else "Company", course["organization_name"]),
        ("Programa" if language == "es" else "Program", PROGRAM_TITLE[language]),
        ("Versión del curso" if language == "es" else "Course version", course["course_version"]),
        ("Finalización" if language == "es" else "Completed on", _format_display_date(course["completed_at"], language)),
        ("ID del documento" if language == "es" else "Document ID", artifact["artifact_id"]),
        ("Código de verificación" if language == "es" else "Verification code", artifact["verification_code"]),
    ]
    review_text = _review_paragraph(language, course.get("review_recommendation") or {})
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=24 * mm,
        bottomMargin=24 * mm,
    )

    if language == "es":
        lead = (
            "Certificado emitido a partir de una inscripción individual verificable dentro del recorrido "
            "formativo básico de HREVN Start."
        )
    else:
        lead = (
            "Certificate issued from an individually traceable enrollment inside the HREVN Start "
            "basic training path."
        )

    story = [
        Paragraph("HREVN Start · Certificado" if language == "es" else "HREVN Start · Certificate", styles["eyebrow"]),
        Paragraph(
            "Certificado de realización de formación básica en IA"
            if language == "es"
            else "Basic AI training completion certificate",
            styles["title"],
        ),
        Paragraph(lead, styles["lead"]),
        _proof_band(artifact["verification_code"], artifact["verification_url"], language, styles),
        Spacer(1, 5 * mm),
        _record_table(summary_rows, styles),
        Spacer(1, 5 * mm),
        Paragraph("Qué acredita" if language == "es" else "What it certifies", styles["section"]),
        Paragraph(ACCREDITATION_STATEMENT[language], styles["body"]),
        Paragraph(IDENTITY_NOTE[language], styles["body"]),
        Spacer(1, 1 * mm),
        Paragraph("Criterio de superación" if language == "es" else "Passing criteria", styles["section"]),
        Paragraph(PASS_RULE[language], styles["body"]),
        Paragraph(
            (
                f"URL de verificación: {artifact['verification_url']}"
                if language == "es" and _verification_record_is_final()
                else f"URL de verificación prevista: {artifact['verification_url']}"
                if language == "es"
                else f"Verification URL: {artifact['verification_url']}"
                if _verification_record_is_final()
                else f"Planned verification URL: {artifact['verification_url']}"
            ),
            styles["body"],
        ),
    ]

    if review_text:
        story.extend(
            [
                Spacer(1, 2 * mm),
                Paragraph(REVIEW_NOTE_PREFIX[language], styles["section"]),
                Paragraph(review_text, styles["body"]),
            ]
        )

    story.extend(
        [
            Spacer(1, 2 * mm),
            Paragraph("Qué no acredita" if language == "es" else "What it does not certify", styles["section"]),
            Paragraph(NON_ACCREDITATION_NOTE[language], styles["body"]),
            Spacer(1, 2 * mm),
            Paragraph("Límite" if language == "es" else "Limit", styles["section"]),
            Paragraph(LEGAL_NOTICE[language], styles["body"]),
            Spacer(1, 2 * mm),
            Paragraph(
                (
                    "Este documento forma parte del modelo documental inicial HREVN Start."
                    if language == "es"
                    else "This document is part of the initial HREVN Start documentary model."
                ),
                styles["note"],
            ),
        ]
    )

    anchor = artifact.get("anchor") or {}
    if anchor.get("status") or anchor.get("network") or anchor.get("transaction_reference"):
        anchor_label = "Registro temporal externo" if language == "es" else "External timestamp record"
        anchor_note = (
            f"{anchor_label}: {_anchor_network_label(anchor.get('network'), language)} · "
            f"{_anchor_status_label(anchor.get('status'), language)} · "
            f"{'Referencia' if language == 'es' else 'Reference'}: {_short_transaction_reference(anchor.get('transaction_reference'))}"
        )
        story.extend(
            [
                Spacer(1, 2 * mm),
                Paragraph(anchor_note, styles["note"]),
            ]
        )

    def draw_page(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(paper)
        canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        canvas.setFillColor(brand)
        canvas.rect(0, A4[1] - 14, A4[0], 14, stroke=0, fill=1)
        canvas.setStrokeColor(line)
        canvas.line(doc.leftMargin, 18 * mm, A4[0] - doc.rightMargin, 18 * mm)
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(doc.leftMargin, 12 * mm, f"HREVN · {settings.public_site_base_url} · contact@hrevn.com")
        canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    target_path.write_bytes(buffer.getvalue())


def issue_course_certificate(enrollment_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            course = _fetch_course_tx(cur, enrollment_id)
            if not course.get("required_course_completed"):
                raise CourseCompletionBlockedError("Required course is not completed yet.")

            cur.execute(
                f"SELECT metadata FROM {_table_enrollments()} WHERE enrollment_id = %s",
                (enrollment_id,),
            )
            metadata_row = cur.fetchone()
            metadata = dict(metadata_row["metadata"] or {}) if metadata_row else {}
            completed_at = course.get("completed_at") or _now_iso()
            artifact, artifact_changed = _ensure_certificate_artifact(metadata, completed_at)
            relative_path = f"certificates/{artifact['artifact_id']}_{course['language']}.pdf"
            target_path = _certificate_file_path(artifact["artifact_id"], course["language"])
            artifact["issued_at"] = artifact.get("issued_at") or completed_at
            anchor_payload = build_course_anchor_payload(
                artifact_id=artifact["artifact_id"],
                verification_code=artifact["verification_code"],
                verification_url=artifact["verification_url"],
                full_name=course["full_name"],
                email=course["email"],
                organization_name=course["organization_name"],
                course_version=course["course_version"],
                completed_at=course.get("completed_at"),
                issued_at=artifact["issued_at"],
                language=course["language"],
                identity_confirmed=bool(course.get("identity_attestation", {}).get("accepted")),
            )
            anchored = anchor_course_artifact(anchor_payload)
            if anchored:
                anchor_record = anchored["anchor_record"]
                artifact["anchor"] = {
                    "root_hash": anchor_record.get("root_hash"),
                    "network": anchor_record.get("network"),
                    "anchor_method": anchor_record.get("anchor_method"),
                    "transaction_reference": anchor_record.get("transaction_reference"),
                    "anchored_at": anchor_record.get("anchored_at"),
                    "status": anchor_record.get("status"),
                    "error": anchor_record.get("error"),
                }
                artifact["anchor_payload_sha256"] = anchored["payload_sha256"]
                artifact["anchor_payload_version"] = "hrevn_start_course_anchor_v1"

            _build_certificate_pdf(course, artifact, target_path)
            artifact["file_path"] = relative_path
            artifact["download_path"] = f"/v1/hrevn-start/course-enrollments/{enrollment_id}/certificate/download"
            metadata["certificate_artifact"] = artifact

            cur.execute(
                f"""
                UPDATE {_table_enrollments()}
                SET
                  certificate_status = 'issued',
                  metadata = %s,
                  last_seen_at = %s
                WHERE enrollment_id = %s
                """,
                (_jsonb(metadata), _now_iso(), enrollment_id),
            )
            _record_activity_tx(
                cur,
                enrollment_id,
                "certificate_issued",
                {
                    "artifact_id": artifact["artifact_id"],
                    "verification_code": artifact["verification_code"],
                    "relative_path": relative_path,
                    "anchor_status": (artifact.get("anchor") or {}).get("status"),
                    "anchor_network": (artifact.get("anchor") or {}).get("network"),
                    "anchor_transaction_reference": (artifact.get("anchor") or {}).get("transaction_reference"),
                },
            )
            if artifact_changed:
                _record_activity_tx(cur, enrollment_id, "certificate_artifact_prepared", artifact)
            _sync_company_participant_from_enrollment_tx(
                cur,
                enrollment_id,
                status="certificate_issued",
                last_seen_at=_now_iso(),
                completed_at=course.get("completed_at"),
                certificate_issued_at=artifact["issued_at"],
            )
            course = _fetch_course_tx(cur, enrollment_id)
            return {
                "course": course,
                "certificate_artifact": course["certificate_artifact"],
                "download_path": artifact["download_path"],
                "filename": f"hrevn-start-certificate-{_slugify_filename(course['full_name'])}.pdf",
                "file_path": target_path,
            }


def resolve_course_certificate_download(enrollment_id: str) -> tuple[Path, str]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            course = _fetch_course_tx(cur, enrollment_id)
            if not course.get("required_course_completed"):
                raise CourseCompletionBlockedError("Required course is not completed yet.")
            artifact = course.get("certificate_artifact") or {}
            artifact_id = artifact.get("artifact_id")
            if not artifact_id:
                result = issue_course_certificate(enrollment_id)
                return result["file_path"], result["filename"]
            path = _certificate_file_path(artifact_id, course["language"])
            if not path.exists():
                result = issue_course_certificate(enrollment_id)
                return result["file_path"], result["filename"]
            return path, f"hrevn-start-certificate-{_slugify_filename(course['full_name'])}.pdf"


def verify_course_certificate_artifact(artifact_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT enrollment_id
                FROM {_table_enrollments()}
                WHERE metadata -> 'certificate_artifact' ->> 'artifact_id' = %s
                """,
                (artifact_id,),
            )
            row = cur.fetchone()
            if not row:
                raise CourseEnrollmentNotFoundError(f"Certificate artifact not found: {artifact_id}")
            course = _fetch_course_tx(cur, str(row["enrollment_id"]))
            artifact = course.get("certificate_artifact") or {}
            if not artifact.get("artifact_id"):
                raise CourseEnrollmentNotFoundError(f"Certificate artifact not found: {artifact_id}")
            return {
                "artifact_id": artifact["artifact_id"],
                "verification_code": artifact["verification_code"],
                "verification_url": artifact["verification_url"],
                "issued_at": artifact["issued_at"],
                "language": course["language"],
                "participant_full_name": course["full_name"],
                "organization_name": course["organization_name"],
                "course_version": course["course_version"],
                "completed_at": course["completed_at"],
                "required_course_completed": course["required_course_completed"],
                "certificate_status": course["certificate_status"],
                "identity_confirmed": bool(course.get("identity_attestation", {}).get("accepted")),
                "review_recommendation": course["review_recommendation"],
                "anchor": artifact.get("anchor"),
            }
