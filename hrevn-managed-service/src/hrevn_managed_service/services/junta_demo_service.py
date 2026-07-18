from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from ..config import settings


JUNTA_DEMO_PROFILE = "junta_andalucia_property_event_v1"
VERIFY_PATH = "/verify/junta-visit/"
AUTO_CLOSE_MINUTES = 60
EventType = Literal["ENTRADA", "INCIDENCIA"]


class JuntaDemoError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _storage_dir() -> Path:
    root = settings.property_demo_storage_dir.parent / "junta_demo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return _storage_dir() / "demo_state.json"


def _photos_root() -> Path:
    root = _storage_dir() / "photos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _event_verify_url(event_id: str) -> str:
    return f"{settings.public_site_base_url}{VERIFY_PATH}?event_id={event_id}"


def _photo_api_path(event_id: str, photo_id: str) -> str:
    return f"/v1/public/junta-demo/events/{event_id}/photos/{photo_id}"


def _photo_public_url(event_id: str, photo_id: str) -> str:
    return f"{settings.public_api_base_url}{_photo_api_path(event_id, photo_id)}"


def _bundle_public_download_url(bundle_id: str) -> str:
    return f"{settings.public_api_base_url}/v1/public/bundles/{bundle_id}/download"


def _bundle_public_sha256_url(bundle_id: str) -> str:
    return f"{settings.public_api_base_url}/v1/public/bundles/{bundle_id}/sha256"


def _building_blueprint() -> list[dict[str, Any]]:
    return [
        {
            "building_id": "ja-building-sevilla-01",
            "name": "Edificio Ilustrativo Cartuja",
            "city": "Sevilla",
            "address_line": "Avenida de Andalucía 24",
            "notice": "Datos ilustrativos para demo institucional.",
        },
        {
            "building_id": "ja-building-malaga-01",
            "name": "Edificio Ilustrativo La Farola",
            "city": "Málaga",
            "address_line": "Calle Pacífico 18",
            "notice": "Datos ilustrativos para demo institucional.",
        },
    ]


def _asset_blueprint() -> list[dict[str, Any]]:
    return [
        {
            "asset_id": "ja-sev-viv-01a",
            "building_id": "ja-building-sevilla-01",
            "asset_code": "SEV-01A",
            "asset_type": "vivienda",
            "floor": "Planta 1",
            "status": "disponible para entrada",
        },
        {
            "asset_id": "ja-sev-viv-02b",
            "building_id": "ja-building-sevilla-01",
            "asset_code": "SEV-02B",
            "asset_type": "vivienda",
            "floor": "Planta 2",
            "status": "ocupada",
        },
        {
            "asset_id": "ja-sev-local-01",
            "building_id": "ja-building-sevilla-01",
            "asset_code": "SEV-L01",
            "asset_type": "local comunitario",
            "floor": "Planta baja",
            "status": "incidencia abierta",
        },
        {
            "asset_id": "ja-mal-viv-01a",
            "building_id": "ja-building-malaga-01",
            "asset_code": "MAL-01A",
            "asset_type": "vivienda",
            "floor": "Planta 1",
            "status": "ocupada",
        },
        {
            "asset_id": "ja-mal-viv-03c",
            "building_id": "ja-building-malaga-01",
            "asset_code": "MAL-03C",
            "asset_type": "vivienda",
            "floor": "Planta 3",
            "status": "disponible para entrada",
        },
        {
            "asset_id": "ja-mal-local-02",
            "building_id": "ja-building-malaga-01",
            "asset_code": "MAL-L02",
            "asset_type": "local de servicio",
            "floor": "Planta baja",
            "status": "revisión técnica",
        },
    ]


def _default_state() -> dict[str, Any]:
    state = {
        "company": {
            "name": "Demo Junta de Andalucía",
            "scope": "Parque público de vivienda",
            "notice": "Datos y edificios ilustrativos para demostración.",
        },
        "buildings": _building_blueprint(),
        "assets": _asset_blueprint(),
        "events": {},
    }
    _seed_historical_events(state)
    return state


def _ensure_state() -> dict[str, Any]:
    path = _state_path()
    if path.exists():
        return json.loads(path.read_text())
    state = _default_state()
    _save_state(state)
    return state


def _save_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _building_by_id(state: dict[str, Any], building_id: str) -> dict[str, Any]:
    for building in state["buildings"]:
        if building["building_id"] == building_id:
            return building
    raise JuntaDemoError(status_code=404, detail="junta_demo_building_not_found")


def _asset_by_id(state: dict[str, Any], asset_id: str) -> dict[str, Any]:
    for asset in state["assets"]:
        if asset["asset_id"] == asset_id:
            return asset
    raise JuntaDemoError(status_code=404, detail="junta_demo_asset_not_found")


def _event_by_id(state: dict[str, Any], event_id: str) -> dict[str, Any]:
    event = state["events"].get(event_id)
    if not event:
        raise JuntaDemoError(status_code=404, detail="junta_demo_event_not_found")
    return event


def _normalize_event_type(event_type: str) -> EventType:
    normalized = event_type.strip().upper()
    if normalized not in {"ENTRADA", "INCIDENCIA"}:
        raise JuntaDemoError(status_code=400, detail="junta_demo_event_type_must_be_entrada_or_incidencia")
    return normalized  # type: ignore[return-value]


def _decorate_photo(event_id: str, photo: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(photo)
    data.pop("file_path", None)
    data["photo_api_path"] = _photo_api_path(event_id, photo["photo_id"])
    data["photo_url"] = _photo_public_url(event_id, photo["photo_id"])
    return data


def _decorate_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bundle:
        return None
    data = deepcopy(bundle)
    data.pop("bundle_path", None)
    bundle_id = data.get("bundle_id")
    if bundle_id:
        data["download_url"] = _bundle_public_download_url(bundle_id)
        data["sha256_url"] = _bundle_public_sha256_url(bundle_id)
    return data


def _decorate_event(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    asset = _asset_by_id(state, event["asset_id"])
    building = _building_by_id(state, asset["building_id"])
    data = deepcopy(event)
    data["asset"] = deepcopy(asset)
    data["building"] = deepcopy(building)
    data["photos"] = [_decorate_photo(event["event_id"], photo) for photo in event.get("photos", [])]
    data["bundle"] = _decorate_bundle(event.get("bundle"))
    return data


def _asset_events(state: dict[str, Any], asset_id: str) -> list[dict[str, Any]]:
    events = [_decorate_event(state, event) for event in state["events"].values() if event["asset_id"] == asset_id]
    events.sort(key=lambda item: item["created_at"], reverse=True)
    return events


def _svg_photo(label: str, event_type: str) -> bytes:
    bg = "#e8efe9" if event_type == "ENTRADA" else "#f3e7df"
    fg = "#1f3429"
    safe_label = label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
  <rect width="1200" height="800" fill="{bg}"/>
  <rect x="90" y="90" width="1020" height="620" rx="28" fill="#fffdf8" stroke="#b8c3ba" stroke-width="6"/>
  <text x="140" y="210" font-family="Arial, sans-serif" font-size="54" font-weight="700" fill="{fg}">Junta de Andalucía · demo</text>
  <text x="140" y="315" font-family="Arial, sans-serif" font-size="46" fill="{fg}">{event_type}</text>
  <text x="140" y="410" font-family="Arial, sans-serif" font-size="38" fill="{fg}">{safe_label}</text>
  <text x="140" y="575" font-family="Arial, sans-serif" font-size="30" fill="#65736a">Imagen ilustrativa generada para evidencia de prueba</text>
</svg>
""".encode("utf-8")


def _store_photo_bytes(*, event_id: str, filename: str, media_type: str, raw: bytes) -> dict[str, Any]:
    photo_id = f"JP-{uuid4().hex[:10]}".upper()
    safe_name = Path(filename.strip() or f"{photo_id}.svg").name
    ext = Path(safe_name).suffix or mimetypes.guess_extension(media_type) or ".jpg"
    event_dir = _photos_root() / event_id
    event_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{photo_id.lower()}-{_slug(Path(safe_name).stem)}{ext}"
    target = event_dir / stored_name
    target.write_bytes(raw)
    return {
        "photo_id": photo_id,
        "filename": safe_name,
        "media_type": media_type,
        "file_path": str(target),
        "relative_path": f"photos/{event_id}/{stored_name}",
        "photo_sha256": hashlib.sha256(raw).hexdigest(),
        "captured_at": _utc_now(),
    }


def _build_event_summary_document(state: dict[str, Any], asset: dict[str, Any], event: dict[str, Any]) -> bytes:
    building = _building_by_id(state, asset["building_id"])
    summary = {
        "demo_notice": "Datos ilustrativos para demostración institucional.",
        "building": building,
        "asset": {
            "asset_id": asset["asset_id"],
            "asset_code": asset["asset_code"],
            "asset_type": asset["asset_type"],
            "floor": asset["floor"],
        },
        "event": {
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "performed_at": event["performed_at"],
            "performed_by": event["performed_by"],
            "summary": event["summary"],
            "closed_at": event["closed_at"],
            "location": event.get("location"),
        },
        "photos": [
            {
                "photo_id": photo["photo_id"],
                "filename": photo["filename"],
                "media_type": photo["media_type"],
                "photo_sha256": photo["photo_sha256"],
                "captured_at": photo["captured_at"],
            }
            for photo in event.get("photos", [])
        ],
    }
    return (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _emit_event_bundle(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    from .bundle_service import create_bundle

    asset = _asset_by_id(state, event["asset_id"])
    building = _building_by_id(state, asset["building_id"])
    first_photo = event["photos"][0]
    document_name = f"{asset['asset_code']}_{event['event_id']}_event_summary.json"
    record = {
        "profile": JUNTA_DEMO_PROFILE,
        "anchor_network": "sepolia",
        "package_title": f"{event['event_type']} · {building['name']} · {asset['asset_code']}",
        "package_summary": "Evento verificable del parque público de vivienda con evidencia fotográfica.",
        "issued_by": event["performed_by"],
        "language": "es",
        "sample_only": True,
        "profile_inputs": {
            "building_name": building["name"],
            "building_address": f"{building['address_line']}, {building['city']}",
            "asset_code": asset["asset_code"],
            "event_type": event["event_type"],
            "event_id": event["event_id"],
            "performed_at": event["performed_at"],
            "performed_by": event["performed_by"],
            "photo_reference": first_photo["photo_id"],
        },
        "documents": [
            {
                "document_id": f"summary-{event['event_id']}",
                "role": "event_summary",
                "filename": document_name,
                "media_type": "application/json",
                "label": "Resumen del evento",
                "content": _build_event_summary_document(state, asset, event),
            }
        ],
        "images": [
            {
                "artifact_id": photo["photo_id"],
                "role": "event_photo",
                "filename": f"{photo['photo_id'].lower()}-{Path(photo['filename']).name}",
                "media_type": photo["media_type"],
                "label": f"{event['event_type']} · {asset['asset_code']} · {photo['filename']}",
                "content": Path(photo["file_path"]).read_bytes(),
            }
            for photo in event["photos"]
        ],
    }
    created = create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")
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
        "verification_url": _event_verify_url(event["event_id"]),
        "bundle_verification_url": f"{settings.public_site_base_url}/verify/evidence-bundle/?bundle_id={created['bundle_id']}",
        "created_at": _utc_now(),
    }


def _seed_historical_events(state: dict[str, Any]) -> None:
    seeds = [
        ("ja-sev-viv-01a", "ENTRADA", "Técnica demo Sevilla", "Entrada documentada antes de puesta a disposición.", "salon-revisado.svg"),
        ("ja-sev-local-01", "INCIDENCIA", "Inspector demo Sevilla", "Incidencia en zona común: humedad localizada.", "humedad-zona-comun.svg"),
        ("ja-mal-viv-03c", "ENTRADA", "Técnico demo Málaga", "Entrada con revisión fotográfica inicial.", "entrada-malaga.svg"),
        ("ja-mal-local-02", "INCIDENCIA", "Inspector demo Málaga", "Incidencia en cuarto de instalaciones.", "instalaciones.svg"),
    ]
    for asset_id, event_type, performed_by, summary, filename in seeds:
        asset = _asset_by_id(state, asset_id)
        event_id = f"JA-{_short_hash(asset_id + event_type + summary).upper()}"
        event = {
            "event_id": event_id,
            "asset_id": asset_id,
            "event_type": event_type,
            "event_status": "draft",
            "performed_at": _utc_now(),
            "performed_by": performed_by,
            "summary": summary,
            "location": {
                "latitude": 37.3891 if asset["building_id"].endswith("sevilla-01") else 36.7213,
                "longitude": -5.9845 if asset["building_id"].endswith("sevilla-01") else -4.4214,
                "accuracy_meters": 18,
                "captured_at": _utc_now(),
                "source": "demo",
            },
            "created_at": _utc_now(),
            "auto_close_at": (datetime.now(timezone.utc) + timedelta(minutes=AUTO_CLOSE_MINUTES))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "closed_at": None,
            "photos": [],
            "bundle": None,
        }
        raw = _svg_photo(f"{asset['asset_code']} · {summary}", event_type)
        event["photos"].append(
            _store_photo_bytes(event_id=event_id, filename=filename, media_type="image/svg+xml", raw=raw)
        )
        event["closed_at"] = _utc_now()
        event["event_status"] = "closed"
        event["bundle"] = _emit_event_bundle(state, event)
        state["events"][event_id] = event


def get_junta_overview() -> dict[str, Any]:
    state = _ensure_state()
    buildings = []
    for building in state["buildings"]:
        assets = [asset for asset in state["assets"] if asset["building_id"] == building["building_id"]]
        buildings.append(
            {
                **deepcopy(building),
                "assets_count": len(assets),
                "events_count": sum(len(_asset_events(state, asset["asset_id"])) for asset in assets),
            }
        )
    assets = []
    for asset in state["assets"]:
        events = _asset_events(state, asset["asset_id"])
        assets.append({**deepcopy(asset), "building": deepcopy(_building_by_id(state, asset["building_id"])), "events": events})
    events = [_decorate_event(state, event) for event in state["events"].values()]
    events.sort(key=lambda item: item["created_at"], reverse=True)
    return {"company": deepcopy(state["company"]), "buildings": buildings, "assets": assets, "events": events}


def get_junta_asset(asset_id: str) -> dict[str, Any]:
    state = _ensure_state()
    asset = deepcopy(_asset_by_id(state, asset_id))
    return {"asset": asset, "building": deepcopy(_building_by_id(state, asset["building_id"])), "events": _asset_events(state, asset_id)}


def get_junta_event(event_id: str) -> dict[str, Any]:
    state = _ensure_state()
    return {"event": _decorate_event(state, _event_by_id(state, event_id))}


def create_junta_event(
    *,
    asset_id: str,
    event_type: str,
    performed_by: str,
    summary: str | None,
    location: dict[str, Any] | None,
) -> dict[str, Any]:
    state = _ensure_state()
    _asset_by_id(state, asset_id)
    normalized_type = _normalize_event_type(event_type)
    event_id = f"JA-{_short_hash(asset_id + normalized_type + _utc_now()).upper()}"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    event = {
        "event_id": event_id,
        "asset_id": asset_id,
        "event_type": normalized_type,
        "event_status": "draft",
        "performed_at": now.isoformat().replace("+00:00", "Z"),
        "performed_by": performed_by.strip() or "Responsable parque público demo",
        "summary": (summary or "").strip(),
        "location": location or {"source": "not_available"},
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "auto_close_at": (now + timedelta(minutes=AUTO_CLOSE_MINUTES)).isoformat().replace("+00:00", "Z"),
        "closed_at": None,
        "photos": [],
        "bundle": None,
    }
    state["events"][event_id] = event
    _save_state(state)
    return {"event": _decorate_event(state, event)}


def add_junta_photo(*, event_id: str, filename: str, media_type: str | None, content_base64: str) -> dict[str, Any]:
    state = _ensure_state()
    event = _event_by_id(state, event_id)
    if event["event_status"] != "draft":
        raise JuntaDemoError(status_code=409, detail="junta_demo_event_already_closed")
    payload = content_base64.strip()
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise JuntaDemoError(status_code=400, detail=f"invalid_photo_payload:{exc}") from exc
    if not raw:
        raise JuntaDemoError(status_code=400, detail="empty_photo_payload")
    photo = _store_photo_bytes(
        event_id=event_id,
        filename=filename,
        media_type=media_type or mimetypes.guess_type(filename)[0] or "image/jpeg",
        raw=raw,
    )
    event["photos"].append(photo)
    _save_state(state)
    return deepcopy(photo)


def close_junta_event(*, event_id: str, summary: str | None) -> dict[str, Any]:
    state = _ensure_state()
    event = _event_by_id(state, event_id)
    if event["event_status"] != "draft":
        raise JuntaDemoError(status_code=409, detail="junta_demo_event_already_closed")
    if not event["photos"]:
        raise JuntaDemoError(status_code=400, detail="junta_demo_event_requires_photo")
    if summary is not None:
        event["summary"] = summary.strip()
    event["closed_at"] = _utc_now()
    event["event_status"] = "closed"
    event["bundle"] = _emit_event_bundle(state, event)
    _save_state(state)
    return {"event": _decorate_event(state, event)}


def resolve_junta_photo(event_id: str, photo_id: str) -> dict[str, Any]:
    state = _ensure_state()
    event = _event_by_id(state, event_id)
    for photo in event.get("photos", []):
        if photo["photo_id"] == photo_id:
            target = Path(photo["file_path"])
            if not target.exists():
                raise JuntaDemoError(status_code=404, detail="junta_demo_photo_file_not_found")
            return {
                "path": target,
                "media_type": photo.get("media_type") or mimetypes.guess_type(target.name)[0] or "image/jpeg",
                "filename": photo.get("filename") or target.name,
            }
    raise JuntaDemoError(status_code=404, detail="junta_demo_photo_not_found")


def get_public_junta_verify_record(event_id: str) -> dict[str, Any]:
    from .bundle_service import verify_bundle_source

    state = _ensure_state()
    event = _event_by_id(state, event_id)
    asset = _asset_by_id(state, event["asset_id"])
    building = _building_by_id(state, asset["building_id"])
    bundle = event.get("bundle")
    if not bundle:
        raise JuntaDemoError(status_code=404, detail="junta_demo_bundle_not_found")
    bundle_verification = verify_bundle_source(bundle["bundle_path"])
    bundle_verification["source"] = bundle["bundle_id"]
    public_event = _decorate_event(state, event)
    return {
        "demo_notice": "Datos ilustrativos para demostración institucional.",
        "verification_status": "valid",
        "building": deepcopy(building),
        "asset": deepcopy(asset),
        "event": public_event,
        "bundle": _decorate_bundle(bundle),
        "bundle_verification": bundle_verification,
    }
