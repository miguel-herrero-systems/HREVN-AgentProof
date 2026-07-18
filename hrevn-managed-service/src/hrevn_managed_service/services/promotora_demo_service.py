from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ..config import settings


CERTIFICATE_PROFILE = "promotora_construction_certificate_v1"
HANDOVER_PROFILE = "promotora_handover_review_v1"
CERTIFICATE_TYPE = "CERTIFICACION_OBRA"
HANDOVER_TYPE = "REPASO_ENTREGA"
SEED_VERSION = "promotora-demo-v1"
VERIFY_PATH = "/verify/promotora-record/"
RecordType = Literal["CERTIFICACION_OBRA", "REPASO_ENTREGA"]

CONSTRUCTION_PARTIDAS = [
    "Movimiento de tierras y explanación",
    "Cimentación y contenciones",
    "Estructura",
    "Cubiertas",
    "Cerramientos y albañilería",
    "Instalación de fontanería y saneamiento",
    "Instalación eléctrica y telecomunicaciones",
    "Instalación de climatización y ventilación",
    "Carpintería exterior y acristalamiento",
    "Carpintería interior",
    "Revestimientos y solados",
    "Pintura y acabados",
    "Aparatos sanitarios y equipamiento de cocina",
    "Ascensores",
    "Red de saneamiento y abastecimiento exterior",
    "Pavimentación y viales",
    "Jardinería y zonas verdes",
    "Cerramiento de parcela y accesos",
]


class PromotoraDemoError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _storage_dir() -> Path:
    root = settings.property_demo_storage_dir.parent / "promotora_demo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return _storage_dir() / "demo_state.json"


def _photos_root() -> Path:
    root = _storage_dir() / "photos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _seed_assets_dir() -> Path:
    configured = os.getenv("HREVN_PROMOTORA_DEMO_SEED_ASSETS_DIR", "/app/assets/promotora-demo").strip()
    candidate = Path(configured)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parents[3] / "assets" / "promotora-demo"


def _record_verify_url(record_id: str) -> str:
    return f"{settings.public_site_base_url}{VERIFY_PATH}?record_id={record_id}"


def _photo_api_path(record_id: str, photo_id: str) -> str:
    return f"/v1/public/promotora-demo/records/{record_id}/photos/{photo_id}"


def _bundle_download_url(bundle_id: str) -> str:
    return f"{settings.public_api_base_url}/v1/public/bundles/{bundle_id}/download"


def _bundle_sha256_url(bundle_id: str) -> str:
    return f"{settings.public_api_base_url}/v1/public/bundles/{bundle_id}/sha256"


def _promotions() -> list[dict[str, Any]]:
    return [
        {
            "promotion_id": "promo-altamar",
            "name": "Residencial Altamar",
            "location": "Santander",
            "portfolio": "obra_en_curso",
            "phase": "Fase inicial",
        },
        {
            "promotion_id": "promo-turia",
            "name": "Residencial Puerta del Turia",
            "location": "Valencia",
            "portfolio": "obra_en_curso",
            "phase": "Estructura",
        },
        {
            "promotion_id": "promo-sarria",
            "name": "Residencial Jardines de Sarrià",
            "location": "Barcelona",
            "portfolio": "obra_en_curso",
            "phase": "Fase final",
        },
        {
            "promotion_id": "promo-alameda",
            "name": "Residencial Mirador de la Alameda",
            "location": "Sevilla",
            "portfolio": "entregada",
            "phase": "Entregada",
        },
        {
            "promotion_id": "promo-riazor",
            "name": "Residencial Torre Riazor",
            "location": "A Coruña",
            "portfolio": "entregada",
            "phase": "Entregada",
        },
        {
            "promotion_id": "promo-acacias",
            "name": "Residencial Las Acacias",
            "location": "Málaga",
            "portfolio": "entregada",
            "phase": "Entregada",
        },
    ]


def _default_state() -> dict[str, Any]:
    return {
        "company": {
            "name": "Promotora inmobiliaria · demo HREVN",
            "notice": "Promociones, clientes y datos exclusivamente ilustrativos.",
        },
        "seed_version": SEED_VERSION,
        "seed_completed": False,
        "promotions": _promotions(),
        "records": {},
    }


def _save_state(state: dict[str, Any]) -> None:
    target = _state_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(target)


def _ensure_state() -> dict[str, Any]:
    path = _state_path()
    if path.exists():
        return json.loads(path.read_text())
    state = _default_state()
    _save_state(state)
    return state


def _promotion_by_id(state: dict[str, Any], promotion_id: str) -> dict[str, Any]:
    for promotion in state["promotions"]:
        if promotion["promotion_id"] == promotion_id:
            return promotion
    raise PromotoraDemoError(404, "promotora_demo_promotion_not_found")


def _record_by_id(state: dict[str, Any], record_id: str) -> dict[str, Any]:
    record = state["records"].get(record_id)
    if not record:
        raise PromotoraDemoError(404, "promotora_demo_record_not_found")
    return record


def _required_text(value: Any, field: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise PromotoraDemoError(400, f"promotora_demo_required_field:{field}")
    return text


def _percentage(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PromotoraDemoError(400, f"promotora_demo_invalid_percentage:{field}")
    number = float(value)
    if number < 0 or number > 100:
        raise PromotoraDemoError(400, f"promotora_demo_percentage_out_of_range:{field}")
    return round(number, 2)


def validate_certificate_content(record: dict[str, Any]) -> None:
    certificate = record.get("certificate")
    if not isinstance(certificate, dict):
        raise PromotoraDemoError(400, "promotora_demo_certificate_header_required")
    for field in ("promotion_name", "location", "period", "certified_at", "certified_by"):
        _required_text(certificate.get(field), field)
    _percentage(certificate.get("global_progress_pct"), "global_progress_pct")

    partidas = record.get("partidas")
    if not isinstance(partidas, list) or len(partidas) != len(CONSTRUCTION_PARTIDAS):
        raise PromotoraDemoError(400, "promotora_demo_certificate_requires_exactly_18_partidas")
    names: list[str] = []
    for index, item in enumerate(partidas):
        if not isinstance(item, dict):
            raise PromotoraDemoError(400, f"promotora_demo_invalid_partida:{index + 1}")
        names.append(_required_text(item.get("partida"), f"partidas.{index + 1}.partida"))
        _percentage(item.get("porcentaje"), f"partidas.{index + 1}.porcentaje")
    if names != CONSTRUCTION_PARTIDAS or len(set(names)) != len(CONSTRUCTION_PARTIDAS):
        raise PromotoraDemoError(400, "promotora_demo_partida_catalog_mismatch")
    if not record.get("photos"):
        raise PromotoraDemoError(400, "promotora_demo_certificate_requires_photo")


def validate_handover_content(record: dict[str, Any]) -> None:
    review = record.get("review")
    if not isinstance(review, dict):
        raise PromotoraDemoError(400, "promotora_demo_review_header_required")
    for field in ("promotion_name", "unit", "client", "reviewed_at", "reviewed_by"):
        _required_text(review.get(field), field)
    defects = record.get("defects")
    if not isinstance(defects, list) or not defects:
        raise PromotoraDemoError(400, "promotora_demo_review_requires_defects")
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            raise PromotoraDemoError(400, f"promotora_demo_invalid_defect:{index + 1}")
        for field in ("item", "descripcion", "ubicacion", "estado"):
            _required_text(defect.get(field), f"defects.{index + 1}.{field}")
    if not record.get("photos"):
        raise PromotoraDemoError(400, "promotora_demo_review_requires_photo")


def _decorate_photo(record_id: str, photo: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(photo)
    data.pop("file_path", None)
    data["photo_api_path"] = _photo_api_path(record_id, photo["photo_id"])
    data["photo_url"] = f"{settings.public_api_base_url}{data['photo_api_path']}"
    return data


def _decorate_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bundle:
        return None
    data = deepcopy(bundle)
    data.pop("bundle_path", None)
    bundle_id = data.get("bundle_id")
    if bundle_id:
        data["download_url"] = _bundle_download_url(bundle_id)
        data["sha256_url"] = _bundle_sha256_url(bundle_id)
    return data


def _decorate_record(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(record)
    data["promotion"] = deepcopy(_promotion_by_id(state, record["promotion_id"]))
    data["photos"] = [_decorate_photo(record["record_id"], photo) for photo in record.get("photos", [])]
    data["bundle"] = _decorate_bundle(record.get("bundle"))
    data.pop("emission_error", None)
    return data


def _store_photo_bytes(
    *, record_id: str, filename: str, media_type: str, raw: bytes, captured_at: str | None = None
) -> dict[str, Any]:
    photo_id = f"PP-{uuid4().hex[:10]}".upper()
    safe_name = Path(filename.strip() or f"{photo_id}.jpg").name
    extension = Path(safe_name).suffix or mimetypes.guess_extension(media_type) or ".jpg"
    record_dir = _photos_root() / record_id
    record_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{photo_id.lower()}{extension.lower()}"
    target = record_dir / stored_name
    target.write_bytes(raw)
    return {
        "photo_id": photo_id,
        "filename": safe_name,
        "media_type": media_type,
        "file_path": str(target),
        "relative_path": f"photos/{record_id}/{stored_name}",
        "photo_sha256": hashlib.sha256(raw).hexdigest(),
        "captured_at": captured_at or _utc_now(),
    }


def _document_bytes(record: dict[str, Any]) -> bytes:
    first_photo = record["photos"][0]
    if record["record_type"] == CERTIFICATE_TYPE:
        payload = {
            "schema_version": "promotora_construction_certificate_document_v1",
            "certificate": deepcopy(record["certificate"]),
            "partidas": deepcopy(record["partidas"]),
            "photo_reference": first_photo["photo_id"],
        }
    else:
        payload = {
            "schema_version": "promotora_handover_review_document_v1",
            "review": deepcopy(record["review"]),
            "defects": deepcopy(record["defects"]),
            "photo_reference": first_photo["photo_id"],
        }
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _emit_record_bundle(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    from .bundle_service import create_bundle

    promotion = _promotion_by_id(state, record["promotion_id"])
    first_photo = record["photos"][0]
    if record["record_type"] == CERTIFICATE_TYPE:
        profile = CERTIFICATE_PROFILE
        document_role = "construction_certificate_report"
        image_role = "construction_site_photo"
        header = record["certificate"]
        profile_inputs = {
            "promotion_name": header["promotion_name"],
            "location": header["location"],
            "period": header["period"],
            "global_progress_pct": header["global_progress_pct"],
            "certified_at": header["certified_at"],
            "certified_by": header["certified_by"],
        }
        title = f"Certificación de obra · {promotion['name']} · {header['period']}"
        summary = f"Certificación mensual con 18 partidas y avance global del {header['global_progress_pct']} %."
        issued_by = header["certified_by"]
        document_name = f"{record['record_id']}_construction_certificate.json"
    else:
        profile = HANDOVER_PROFILE
        document_role = "handover_review_report"
        image_role = "handover_defect_photo"
        header = record["review"]
        profile_inputs = {
            "promotion_name": header["promotion_name"],
            "unit": header["unit"],
            "client": header["client"],
            "reviewed_at": header["reviewed_at"],
            "reviewed_by": header["reviewed_by"],
        }
        title = f"Repaso de entrega · {promotion['name']} · {header['unit']}"
        summary = f"Repaso de vivienda nueva con {len(record['defects'])} desperfectos documentados."
        issued_by = header["reviewed_by"]
        document_name = f"{record['record_id']}_handover_review.json"

    bundle_record = {
        "profile": profile,
        "anchor_network": "sepolia",
        "package_title": title,
        "package_summary": summary,
        "issued_by": issued_by,
        "language": "es",
        "sample_only": True,
        "profile_inputs": profile_inputs,
        "documents": [
            {
                "document_id": f"report-{record['record_id']}",
                "role": document_role,
                "filename": document_name,
                "media_type": "application/json",
                "label": title,
                "authoritative": True,
                "content": _document_bytes(record),
            }
        ],
        "images": [
            {
                "artifact_id": photo["photo_id"],
                "role": image_role,
                "filename": f"{photo['photo_id'].lower()}-{Path(photo['filename']).name}",
                "media_type": photo["media_type"],
                "label": f"{promotion['name']} · {photo['filename']}",
                "authoritative": True,
                "content": Path(photo["file_path"]).read_bytes(),
            }
            for photo in record["photos"]
        ],
    }
    if first_photo["photo_id"] not in _document_bytes(record).decode("utf-8"):
        raise PromotoraDemoError(500, "promotora_demo_photo_reference_not_serialized")

    created = create_bundle(record=bundle_record, traces=[], bundle_mode="evidence_bundle_eb1")
    return {
        "bundle_id": created["bundle_id"],
        "record_id": created["record_id"],
        "bundle_path": created["bundle_path"],
        "root_hash": created.get("root_hash"),
        "signature_status": created.get("signature_status"),
        "signature_algorithm": created.get("signature_algorithm"),
        "signature_public_key_id": created.get("signature_public_key_id"),
        "anchor_status": created.get("anchor_status"),
        "anchor": created.get("anchor"),
        "verification_url": _record_verify_url(record["record_id"]),
        "bundle_verification_url": (
            f"{settings.public_site_base_url}/verify/evidence-bundle/?bundle_id={created['bundle_id']}"
        ),
        "created_at": _utc_now(),
    }


def get_promotora_overview() -> dict[str, Any]:
    state = _ensure_state()
    records = [_decorate_record(state, item) for item in state["records"].values() if item.get("status") == "closed"]
    records.sort(key=lambda item: item.get("closed_at") or item["created_at"], reverse=True)
    promotions = []
    for promotion in state["promotions"]:
        count = sum(1 for record in records if record["promotion_id"] == promotion["promotion_id"])
        promotions.append({**deepcopy(promotion), "records_count": count})
    return {
        "company": deepcopy(state["company"]),
        "seed_completed": bool(state.get("seed_completed")),
        "partida_catalog": list(CONSTRUCTION_PARTIDAS),
        "promotions": promotions,
        "records": records,
    }


def get_promotora_record(record_id: str) -> dict[str, Any]:
    state = _ensure_state()
    return {"record": _decorate_record(state, _record_by_id(state, record_id))}


def create_certificate(
    *, promotion_id: str, period: str, global_progress_pct: float, certified_at: str,
    certified_by: str, partidas: list[dict[str, Any]]
) -> dict[str, Any]:
    state = _ensure_state()
    promotion = _promotion_by_id(state, promotion_id)
    if promotion["portfolio"] != "obra_en_curso":
        raise PromotoraDemoError(400, "promotora_demo_certificate_requires_active_project")
    record_id = f"PC-{uuid4().hex[:10]}".upper()
    record = {
        "record_id": record_id,
        "record_type": CERTIFICATE_TYPE,
        "profile": CERTIFICATE_PROFILE,
        "promotion_id": promotion_id,
        "status": "draft",
        "certificate": {
            "promotion_name": promotion["name"],
            "location": promotion["location"],
            "period": _required_text(period, "period"),
            "global_progress_pct": _percentage(global_progress_pct, "global_progress_pct"),
            "certified_at": _required_text(certified_at, "certified_at"),
            "certified_by": _required_text(certified_by, "certified_by"),
        },
        "partidas": deepcopy(partidas),
        "photos": [],
        "bundle": None,
        "created_at": _utc_now(),
        "closed_at": None,
    }
    state["records"][record_id] = record
    _save_state(state)
    return {"record": _decorate_record(state, record)}


def create_handover_review(
    *, promotion_id: str, unit: str, client: str, reviewed_at: str,
    reviewed_by: str, defects: list[dict[str, Any]]
) -> dict[str, Any]:
    state = _ensure_state()
    promotion = _promotion_by_id(state, promotion_id)
    if promotion["portfolio"] != "entregada":
        raise PromotoraDemoError(400, "promotora_demo_review_requires_delivered_promotion")
    record_id = f"PR-{uuid4().hex[:10]}".upper()
    record = {
        "record_id": record_id,
        "record_type": HANDOVER_TYPE,
        "profile": HANDOVER_PROFILE,
        "promotion_id": promotion_id,
        "status": "draft",
        "review": {
            "promotion_name": promotion["name"],
            "unit": _required_text(unit, "unit"),
            "client": _required_text(client, "client"),
            "reviewed_at": _required_text(reviewed_at, "reviewed_at"),
            "reviewed_by": _required_text(reviewed_by, "reviewed_by"),
        },
        "defects": deepcopy(defects),
        "photos": [],
        "bundle": None,
        "created_at": _utc_now(),
        "closed_at": None,
    }
    state["records"][record_id] = record
    _save_state(state)
    return {"record": _decorate_record(state, record)}


def add_promotora_photo(
    *, record_id: str, filename: str, media_type: str | None, content_base64: str
) -> dict[str, Any]:
    state = _ensure_state()
    record = _record_by_id(state, record_id)
    if record["status"] != "draft":
        raise PromotoraDemoError(409, "promotora_demo_record_not_editable")
    payload = content_base64.strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise PromotoraDemoError(400, "promotora_demo_invalid_photo_payload") from exc
    if not raw:
        raise PromotoraDemoError(400, "promotora_demo_empty_photo_payload")
    photo = _store_photo_bytes(
        record_id=record_id,
        filename=filename,
        media_type=media_type or mimetypes.guess_type(filename)[0] or "image/jpeg",
        raw=raw,
    )
    record["photos"].append(photo)
    _save_state(state)
    return _decorate_photo(record_id, photo)


def close_promotora_record(record_id: str) -> dict[str, Any]:
    state = _ensure_state()
    record = _record_by_id(state, record_id)
    if record["status"] != "draft":
        raise PromotoraDemoError(409, "promotora_demo_record_already_closed_or_emitting")
    if record["record_type"] == CERTIFICATE_TYPE:
        validate_certificate_content(record)
    elif record["record_type"] == HANDOVER_TYPE:
        validate_handover_content(record)
    else:
        raise PromotoraDemoError(400, "promotora_demo_unknown_record_type")

    # Persist the intent before the transaction. A restart cannot silently repeat an uncertain emission.
    record["status"] = "emitting"
    record["emission_started_at"] = _utc_now()
    _save_state(state)
    try:
        record["bundle"] = _emit_record_bundle(state, record)
        if settings.hrevn_eb_signing_private_key and record["bundle"].get("signature_status") != "signed":
            raise PromotoraDemoError(502, "promotora_demo_signature_failed")
        if settings.hrevn_eb_anchor_emit_real and record["bundle"].get("anchor_status") != "anchored":
            raise PromotoraDemoError(502, "promotora_demo_anchor_failed")
    except Exception as exc:
        record["status"] = "emission_failed"
        record["emission_error"] = type(exc).__name__
        _save_state(state)
        raise
    record["status"] = "closed"
    record["closed_at"] = _utc_now()
    record.pop("emission_error", None)
    _save_state(state)
    return {"record": _decorate_record(state, record)}


def resolve_promotora_photo(record_id: str, photo_id: str) -> dict[str, Any]:
    state = _ensure_state()
    record = _record_by_id(state, record_id)
    for photo in record.get("photos", []):
        if photo["photo_id"] == photo_id:
            target = Path(photo["file_path"])
            if not target.exists():
                raise PromotoraDemoError(404, "promotora_demo_photo_file_not_found")
            return {
                "path": target,
                "media_type": photo.get("media_type") or "image/png",
                "filename": photo.get("filename") or target.name,
            }
    raise PromotoraDemoError(404, "promotora_demo_photo_not_found")


def get_public_promotora_verify_record(record_id: str) -> dict[str, Any]:
    from .bundle_service import verify_bundle_source

    state = _ensure_state()
    record = _record_by_id(state, record_id)
    bundle = record.get("bundle")
    if not bundle:
        raise PromotoraDemoError(404, "promotora_demo_bundle_not_found")
    verification = verify_bundle_source(bundle["bundle_path"])
    verification["source"] = bundle["bundle_id"]
    return {
        "demo_notice": state["company"]["notice"],
        "verification_status": "valid" if verification.get("valid") else "invalid",
        "record": _decorate_record(state, record),
        "bundle": _decorate_bundle(bundle),
        "bundle_verification": verification,
    }


def _partidas(values: list[float]) -> list[dict[str, Any]]:
    return [
        {"partida": name, "porcentaje": float(value)}
        for name, value in zip(CONSTRUCTION_PARTIDAS, values, strict=True)
    ]


def _seed_specs() -> list[dict[str, Any]]:
    return [
        {
            "record_id": "PC-ALTAMAR-2026-07",
            "record_type": CERTIFICATE_TYPE,
            "promotion_id": "promo-altamar",
            "certified_at": "2026-07-02T09:15:00Z",
            "certified_by": "Laura Fernández · técnica ilustrativa",
            "period": "2026-07",
            "values": [80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "asset": "cert-altamar-earthworks.png",
        },
        {
            "record_id": "PC-TURIA-2026-07",
            "record_type": CERTIFICATE_TYPE,
            "promotion_id": "promo-turia",
            "certified_at": "2026-07-04T10:30:00Z",
            "certified_by": "Javier Pons · técnico ilustrativo",
            "period": "2026-07",
            "values": [100, 100, 55, 0, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 20, 0, 0, 0],
            "asset": "cert-turia-structure.png",
        },
        {
            "record_id": "PC-SARRIA-2026-07",
            "record_type": CERTIFICATE_TYPE,
            "promotion_id": "promo-sarria",
            "certified_at": "2026-07-06T08:45:00Z",
            "certified_by": "Marta Rius · técnica ilustrativa",
            "period": "2026-07",
            "values": [100, 100, 100, 95, 95, 85, 85, 80, 85, 70, 75, 60, 55, 65, 90, 70, 45, 75],
            "asset": "cert-sarria-final.png",
        },
        {
            "record_id": "PR-ALAMEDA-2A",
            "record_type": HANDOVER_TYPE,
            "promotion_id": "promo-alameda",
            "reviewed_at": "2026-06-24T11:20:00Z",
            "reviewed_by": "Ana Beltrán · técnica ilustrativa",
            "unit": "Vivienda 2A",
            "client": "Clara Gómez · cliente ilustrativa",
            "defects": [
                {"item": "D-01", "descripcion": "Rozadura y pequeño desconchado en puerta lacada nueva.", "ubicacion": "Dormitorio principal", "estado": "Pendiente"},
                {"item": "D-02", "descripcion": "El grifo del lavabo produce un goteo lento.", "ubicacion": "Baño principal", "estado": "Pendiente"},
                {"item": "D-03", "descripcion": "La persiana ofrece resistencia durante la subida.", "ubicacion": "Salón", "estado": "Pendiente"},
            ],
            "asset": "review-alameda-door.png",
        },
        {
            "record_id": "PR-RIAZOR-5C",
            "record_type": HANDOVER_TYPE,
            "promotion_id": "promo-riazor",
            "reviewed_at": "2026-06-27T09:40:00Z",
            "reviewed_by": "Diego Varela · técnico ilustrativo",
            "unit": "Vivienda 5C",
            "client": "Martín Seoane · cliente ilustrativo",
            "defects": [
                {"item": "D-01", "descripcion": "El grifo nuevo no cierra completamente y gotea sobre el lavabo.", "ubicacion": "Baño secundario", "estado": "Pendiente"},
                {"item": "D-02", "descripcion": "Falta remate continuo de silicona en el encuentro con pared.", "ubicacion": "Plato de ducha", "estado": "Pendiente"},
                {"item": "D-03", "descripcion": "Puerta de mueble ligeramente desalineada.", "ubicacion": "Cocina", "estado": "Pendiente"},
            ],
            "asset": "review-riazor-tap.png",
        },
        {
            "record_id": "PR-ACACIAS-1B",
            "record_type": HANDOVER_TYPE,
            "promotion_id": "promo-acacias",
            "reviewed_at": "2026-07-01T12:05:00Z",
            "reviewed_by": "Nuria Salas · técnica ilustrativa",
            "unit": "Vivienda 1B",
            "client": "Lucía Moreno · cliente ilustrativa",
            "defects": [
                {"item": "D-01", "descripcion": "Varias lamas de la persiana nueva quedan desalineadas y se atascan.", "ubicacion": "Dormitorio 2", "estado": "Pendiente"},
                {"item": "D-02", "descripcion": "Junta abierta en un tramo corto de rodapié.", "ubicacion": "Pasillo", "estado": "Pendiente"},
                {"item": "D-03", "descripcion": "Pequeña falta de rejuntado entre dos piezas.", "ubicacion": "Terraza", "estado": "Pendiente"},
            ],
            "asset": "review-acacias-shutter.png",
        },
    ]


def seed_promotora_demo_once() -> dict[str, Any]:
    state = _ensure_state()
    if state.get("seed_completed") and state.get("seed_version") == SEED_VERSION:
        return get_promotora_overview()
    assets_dir = _seed_assets_dir()
    specs = _seed_specs()
    missing_assets = [spec["asset"] for spec in specs if not (assets_dir / spec["asset"]).is_file()]
    if missing_assets:
        raise PromotoraDemoError(500, f"promotora_demo_seed_assets_missing:{','.join(missing_assets)}")

    for spec in specs:
        existing = state["records"].get(spec["record_id"])
        if existing:
            if existing.get("status") == "closed" and existing.get("bundle"):
                continue
            raise PromotoraDemoError(409, f"promotora_demo_seed_requires_reconciliation:{spec['record_id']}")
        promotion = _promotion_by_id(state, spec["promotion_id"])
        record: dict[str, Any] = {
            "record_id": spec["record_id"],
            "record_type": spec["record_type"],
            "profile": CERTIFICATE_PROFILE if spec["record_type"] == CERTIFICATE_TYPE else HANDOVER_PROFILE,
            "promotion_id": spec["promotion_id"],
            "status": "draft",
            "photos": [],
            "bundle": None,
            "created_at": spec.get("certified_at") or spec.get("reviewed_at"),
            "closed_at": None,
            "seeded": True,
        }
        if spec["record_type"] == CERTIFICATE_TYPE:
            partidas = _partidas(spec["values"])
            record["certificate"] = {
                "promotion_name": promotion["name"],
                "location": promotion["location"],
                "period": spec["period"],
                "global_progress_pct": round(sum(spec["values"]) / len(CONSTRUCTION_PARTIDAS), 2),
                "certified_at": spec["certified_at"],
                "certified_by": spec["certified_by"],
            }
            record["partidas"] = partidas
            captured_at = spec["certified_at"]
        else:
            record["review"] = {
                "promotion_name": promotion["name"],
                "unit": spec["unit"],
                "client": spec["client"],
                "reviewed_at": spec["reviewed_at"],
                "reviewed_by": spec["reviewed_by"],
            }
            record["defects"] = deepcopy(spec["defects"])
            captured_at = spec["reviewed_at"]
        raw = (assets_dir / spec["asset"]).read_bytes()
        record["photos"].append(
            _store_photo_bytes(
                record_id=record["record_id"],
                filename=spec["asset"],
                media_type="image/png",
                raw=raw,
                captured_at=captured_at,
            )
        )
        state["records"][record["record_id"]] = record
        _save_state(state)
        close_promotora_record(record["record_id"])
        state = _ensure_state()

    state["seed_completed"] = True
    state["seed_version"] = SEED_VERSION
    state["seed_completed_at"] = _utc_now()
    _save_state(state)
    return get_promotora_overview()
