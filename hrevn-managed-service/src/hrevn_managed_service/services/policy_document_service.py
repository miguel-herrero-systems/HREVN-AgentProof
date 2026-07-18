from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import secrets
from typing import Any
from uuid import uuid4

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import settings
from .db import connect_dict
from .hrevn_start_anchor_service import anchor_policy_artifact, build_policy_anchor_payload
from .policy_service import (
    PolicyCaseNotFoundError,
    PolicyDocumentNotFoundError,
    PolicySubmissionNotFoundError,
    _fetch_case_summary_tx,
    _fetch_document_tx,
    _fetch_submission_tx,
    _record_activity_tx,
    _table_cases,
    _table_documents,
)


class PolicyDocumentIssueBlockedError(RuntimeError):
    error_code = "policy_document_issue_blocked"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _jsonb(value: Any):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _policy_documents_dir() -> Path:
    target = settings.policy_storage_dir / "documents"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _policy_pdf_path(artifact_id: str, language: str) -> Path:
    suffix = "es" if language == "es" else "en"
    return _policy_documents_dir() / f"{artifact_id}_{suffix}.pdf"


def _slugify_filename(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "policy"


def _make_verification_code(issued_at: str) -> str:
    compact_date = issued_at[2:4] + issued_at[5:7]
    suffix = secrets.token_hex(2).upper()
    return f"HST-POL-{compact_date}-{suffix}"


def _make_verification_url(artifact_id: str) -> str:
    return f"{settings.public_site_base_url}{settings.policy_verification_path_prefix}/?artifact_id={artifact_id}"


def _verification_record_is_final() -> bool:
    return settings.public_site_base_url.rstrip("/") == "https://hrevn.com"


def _styles():
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
            spaceAfter=8,
        ),
        "lead": ParagraphStyle(
            "Lead",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#5f5149"),
            spaceAfter=7,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=14.2,
            textColor=colors.HexColor("#4d433d"),
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14.5,
            leading=17.5,
            textColor=colors.HexColor("#241b18"),
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=13.8,
            leftIndent=12,
            firstLineIndent=-7,
            bulletIndent=0,
            textColor=colors.HexColor("#4d433d"),
            spaceAfter=4,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=styles["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=9.2,
            leading=12.8,
            textColor=colors.HexColor("#6d6059"),
            spaceAfter=6,
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


def _verification_qr_block(url: str, language: str, styles: dict[str, ParagraphStyle]) -> Table:
    widget = qr.QrCodeWidget(url)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    size = 34 * mm
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    label = (
        "Escanea este código para abrir el registro verificable del documento."
        if language == "es" and _verification_record_is_final()
        else "Escanea este código para abrir el registro de verificación previsto del documento."
        if language == "es"
        else "Scan this code to open the planned verification record for this document."
    )
    table = Table([[drawing, Paragraph(label, styles["body"])]], colWidths=[40 * mm, 120 * mm])
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
    labels_es = {
        "sepolia": "Ethereum Sepolia",
        "base-sepolia": "Base Sepolia",
        "base": "Base",
    }
    labels_en = {
        "sepolia": "Ethereum Sepolia",
        "base-sepolia": "Base Sepolia",
        "base": "Base",
    }
    if not network:
        return "—"
    return (labels_es if language == "es" else labels_en).get(network, network)


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


def _build_pdf_bytes(policy_case: dict[str, Any], policy_document: dict[str, Any], artifact: dict[str, Any]) -> bytes:
    language = policy_document["language"]
    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=24 * mm,
        bottomMargin=22 * mm,
    )

    rendered = policy_document.get("rendered_content") or {}
    summary_rows = [
        ("Empresa" if language == "es" else "Company", policy_case["organization_legal_name"]),
        ("CIF/NIF" if language == "es" else "Tax ID", policy_case["organization_tax_id"]),
        ("Representante" if language == "es" else "Representative", policy_case["representative_name"]),
        ("Cargo" if language == "es" else "Role", policy_case["representative_role"]),
        ("Versión" if language == "es" else "Version", policy_document["policy_version"]),
        ("Fecha de emisión" if language == "es" else "Issued on", (policy_document.get("issued_at") or "")[:10]),
        ("ID del documento" if language == "es" else "Document ID", artifact["artifact_id"]),
        ("Código de verificación" if language == "es" else "Verification code", artifact["verification_code"]),
    ]

    lead = (
        "Documento interno emitido a partir del cuestionario de política de HREVN Start."
        if language == "es"
        else "Internal document issued from the HREVN Start policy questionnaire."
    )

    story: list[Any] = [
        Paragraph("HREVN Start · Política interna inicial" if language == "es" else "HREVN Start · Initial internal policy", styles["eyebrow"]),
        Paragraph(rendered.get("title") or policy_document["title"], styles["title"]),
        Paragraph(lead, styles["lead"]),
        _summary_table(summary_rows, styles),
        Spacer(1, 7 * mm),
        Paragraph(rendered.get("summary") or "", styles["body"]),
        Spacer(1, 5 * mm),
    ]

    for section in rendered.get("sections") or []:
      story.append(Paragraph(section.get("title") or "", styles["section"]))
      body_lines = section.get("body") or []
      item_lines = section.get("items") or []
      if item_lines:
          intro_lines = body_lines[: max(0, len(body_lines) - len(item_lines))]
          if not intro_lines and body_lines:
              intro_lines = body_lines[:1]
          for line in intro_lines:
              story.append(Paragraph(line, styles["body"]))
          for item in item_lines:
              story.append(Paragraph(item, styles["bullet"], bulletText="•"))
      else:
          for line in body_lines:
              story.append(Paragraph(line, styles["body"]))
      story.append(Spacer(1, 2.5 * mm))

    story.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph(
                "Registro verificable" if language == "es" and _verification_record_is_final() else
                "Registro verificable previsto" if language == "es" else
                "Planned verification record",
                styles["section"],
            ),
            _verification_qr_block(artifact["verification_url"], language, styles),
            Paragraph(
                (
                    f"URL de verificación: {artifact['verification_url']}"
                    if language == "es" and _verification_record_is_final()
                    else f"URL de verificación prevista: {artifact['verification_url']}"
                    if language == "es"
                    else f"Planned verification URL: {artifact['verification_url']}"
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

    def draw_page(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#f8f1e8"))
        canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        canvas.setStrokeColor(colors.HexColor("#e0cfbf"))
        canvas.setLineWidth(1)
        canvas.line(pdf_doc.leftMargin, A4[1] - 18 * mm, A4[0] - pdf_doc.rightMargin, A4[1] - 18 * mm)
        canvas.setFillColor(colors.HexColor("#b7633b"))
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(pdf_doc.leftMargin, A4[1] - 14 * mm, "HREVN")
        canvas.setFillColor(colors.HexColor("#7a6a60"))
        canvas.setFont("Helvetica", 8.5)
        canvas.drawString(pdf_doc.leftMargin, 11 * mm, f"HREVN · {settings.public_site_base_url} · contact@hrevn.com")
        canvas.drawRightString(A4[0] - pdf_doc.rightMargin, 11 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buffer.getvalue()


def _anchor_columns(anchor_record: dict[str, Any] | None) -> dict[str, Any]:
    if not anchor_record:
        return {
            "anchor_network": None,
            "anchor_status": None,
            "anchor_method": None,
            "anchor_transaction_reference": None,
            "anchored_at": None,
            "anchor_error": None,
        }

    return {
        "anchor_network": anchor_record.get("network"),
        "anchor_status": anchor_record.get("status"),
        "anchor_method": anchor_record.get("anchor_method"),
        "anchor_transaction_reference": anchor_record.get("transaction_reference"),
        "anchored_at": anchor_record.get("anchored_at"),
        "anchor_error": anchor_record.get("error"),
    }


def issue_policy_document(policy_case_id: str, policy_document_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            policy_case = _fetch_case_summary_tx(cur, policy_case_id)
            policy_document = _fetch_document_tx(cur, policy_document_id)
            if policy_document["policy_case_id"] != policy_case_id:
                raise PolicyDocumentNotFoundError(
                    f"Policy document {policy_document_id} does not belong to policy case {policy_case_id}"
                )
            if policy_document["status"] in {"superseded", "revoked", "failed"}:
                raise PolicyDocumentIssueBlockedError("This policy document cannot be issued in its current state.")

            issued_at = policy_document.get("issued_at") or _now_iso()
            artifact_id = policy_document.get("artifact", {}).get("artifact_id") or str(uuid4())
            verification_code = policy_document.get("artifact", {}).get("verification_code") or _make_verification_code(issued_at)
            verification_url = policy_document.get("artifact", {}).get("verification_url") or _make_verification_url(artifact_id)
            artifact = {
                "artifact_id": artifact_id,
                "verification_code": verification_code,
                "verification_url": verification_url,
            }
            anchor_payload = build_policy_anchor_payload(
                artifact_id=artifact_id,
                verification_code=verification_code,
                verification_url=verification_url,
                organization_name=policy_case["organization_legal_name"],
                organization_tax_id=policy_case["organization_tax_id"],
                representative_name=policy_case["representative_name"],
                representative_role=policy_case["representative_role"],
                policy_version=policy_document["policy_version"],
                issue_date=(policy_document.get("issued_at") or issued_at)[:10],
                effective_date=(policy_document.get("context_snapshot") or {}).get("policy_effective_date"),
                language=policy_document["language"],
            )
            anchored = anchor_policy_artifact(anchor_payload)
            anchor_record = anchored["anchor_record"] if anchored else None
            anchor_columns = _anchor_columns(anchor_record)
            if anchor_record:
                artifact["anchor"] = {
                    "root_hash": anchor_record.get("root_hash"),
                    "network": anchor_record.get("network"),
                    "anchor_method": anchor_record.get("anchor_method"),
                    "transaction_reference": anchor_record.get("transaction_reference"),
                    "anchored_at": anchor_record.get("anchored_at"),
                    "status": anchor_record.get("status"),
                    "error": anchor_record.get("error"),
                }

            pdf_bytes = _build_pdf_bytes(policy_case, policy_document, artifact)
            file_hash = sha256(pdf_bytes).hexdigest()
            target_path = _policy_pdf_path(artifact_id, policy_document["language"])
            target_path.write_bytes(pdf_bytes)
            relative_path = f"documents/{artifact_id}_{policy_document['language']}.pdf"
            document_metadata = dict(policy_document.get("metadata") or {})
            if anchored:
                document_metadata["anchor_payload_sha256"] = anchored["payload_sha256"]
                document_metadata["anchor_payload_version"] = "hrevn_start_policy_anchor_v1"

            cur.execute(
                f"""
                UPDATE {_table_documents()}
                SET
                  status = 'issued',
                  issued_at = %s,
                  storage_path = %s,
                  sha256 = %s,
                  artifact_id = %s,
                  verification_code = %s,
                  verification_url = %s,
                  anchor_network = %s,
                  anchor_status = %s,
                  anchor_method = %s,
                  anchor_transaction_reference = %s,
                  anchored_at = %s,
                  anchor_error = %s,
                  metadata = %s
                WHERE policy_document_id = %s
                """,
                (
                    issued_at,
                    relative_path,
                    file_hash,
                    artifact_id,
                    verification_code,
                    verification_url,
                    anchor_columns["anchor_network"],
                    anchor_columns["anchor_status"],
                    anchor_columns["anchor_method"],
                    anchor_columns["anchor_transaction_reference"],
                    anchor_columns["anchored_at"],
                    anchor_columns["anchor_error"],
                    _jsonb(document_metadata),
                    policy_document_id,
                ),
            )
            cur.execute(
                f"""
                UPDATE {_table_cases()}
                SET
                  status = 'policy_issued',
                  current_policy_document_id = %s
                WHERE policy_case_id = %s
                """,
                (policy_document_id, policy_case_id),
            )
            _record_activity_tx(
                cur,
                policy_case_id,
                "policy_document_issued",
                {
                    "policy_document_id": policy_document_id,
                    "artifact_id": artifact_id,
                    "verification_code": verification_code,
                    "relative_path": relative_path,
                    "sha256": file_hash,
                    "anchor_status": anchor_columns["anchor_status"],
                    "anchor_network": anchor_columns["anchor_network"],
                    "anchor_transaction_reference": anchor_columns["anchor_transaction_reference"],
                },
                actor_type="system",
                policy_document_id=policy_document_id,
            )
            updated_case = _fetch_case_summary_tx(cur, policy_case_id)
            updated_document = _fetch_document_tx(cur, policy_document_id)
            return {
                "policy_case": updated_case,
                "policy_document": updated_document,
                "download_path": f"/v1/hrevn-start/policy-cases/{policy_case_id}/documents/{policy_document_id}/download",
                "filename": f"hrevn-start-policy-{_slugify_filename(policy_case['organization_legal_name'])}.pdf",
                "file_path": target_path,
            }


def resolve_policy_document_download(policy_case_id: str, policy_document_id: str) -> tuple[Path, str]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            policy_case = _fetch_case_summary_tx(cur, policy_case_id)
            policy_document = _fetch_document_tx(cur, policy_document_id)
            if policy_document["policy_case_id"] != policy_case_id:
                raise PolicyDocumentNotFoundError(
                    f"Policy document {policy_document_id} does not belong to policy case {policy_case_id}"
                )
            artifact_id = policy_document.get("artifact", {}).get("artifact_id")
            if not artifact_id or not policy_document.get("storage_path"):
                result = issue_policy_document(policy_case_id, policy_document_id)
                return result["file_path"], result["filename"]
            path = _policy_pdf_path(artifact_id, policy_document["language"])
            if not path.exists():
                result = issue_policy_document(policy_case_id, policy_document_id)
                return result["file_path"], result["filename"]
            return path, f"hrevn-start-policy-{_slugify_filename(policy_case['organization_legal_name'])}.pdf"


def verify_policy_document_artifact(artifact_id: str) -> dict[str, Any]:
    with connect_dict() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT policy_document_id
                FROM {_table_documents()}
                WHERE artifact_id = %s
                """,
                (artifact_id,),
            )
            row = cur.fetchone()
            if not row:
                raise PolicyDocumentNotFoundError(f"Policy document artifact not found: {artifact_id}")

            policy_document = _fetch_document_tx(cur, str(row["policy_document_id"]))
            if not policy_document.get("artifact", {}).get("artifact_id"):
                raise PolicyDocumentNotFoundError(f"Policy document artifact not found: {artifact_id}")

            policy_case = _fetch_case_summary_tx(cur, policy_document["policy_case_id"])
            submission = None
            if policy_document.get("source_submission_id"):
                try:
                    submission = _fetch_submission_tx(cur, policy_document["source_submission_id"])
                except PolicySubmissionNotFoundError:
                    submission = None

            artifact = policy_document["artifact"]
            context = policy_document.get("context_snapshot") or {}
            return {
                "artifact_id": artifact["artifact_id"],
                "verification_code": artifact["verification_code"],
                "verification_url": artifact["verification_url"],
                "issued_at": policy_document["issued_at"],
                "language": policy_document["language"],
                "organization_name": policy_case["organization_legal_name"],
                "organization_tax_id": policy_case["organization_tax_id"],
                "representative_name": policy_case["representative_name"],
                "representative_role": policy_case["representative_role"],
                "representative_email": policy_case["representative_email"],
                "policy_version": policy_document["policy_version"],
                "document_kind": policy_document["document_kind"],
                "document_status": policy_document["status"],
                "scope_result": policy_document["scope_result"],
                "effective_date": context.get("policy_effective_date"),
                "issue_date": context.get("policy_issue_date"),
                "sha256": artifact.get("sha256"),
                "representative_declaration_confirmed": bool(
                    submission.get("representative_declaration_confirmed") if submission else False
                ),
                "anchor": artifact.get("anchor"),
            }
