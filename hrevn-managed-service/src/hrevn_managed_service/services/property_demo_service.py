from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ..config import settings
from .bundle_service import create_bundle, resolve_bundle_download, verify_bundle_source


PROPERTY_DEMO_PROFILE = "property_manager_rental_visit_v1"
VERIFY_PATH = "/verify/property-visit/"
AUTO_CLOSE_MINUTES = 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _storage_dir() -> Path:
    root = settings.property_demo_storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path() -> Path:
    return _storage_dir() / "demo_state.json"


def _photos_root() -> Path:
    root = _storage_dir() / "photos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _visit_verify_url(visit_id: str) -> str:
    return f"{settings.public_site_base_url}{VERIFY_PATH}?visit_id={visit_id}"


def _photo_api_path(visit_id: str, photo_id: str) -> str:
    return f"/v1/public/property-demo/visits/{visit_id}/photos/{photo_id}"


def _photo_public_url(visit_id: str, photo_id: str) -> str:
    return f"{settings.public_api_base_url}{_photo_api_path(visit_id, photo_id)}"


def _company_blueprint() -> dict[str, Any]:
    return {
        "company_id": "company-demo-pm-01",
        "name": "HREVN Property Operations Demo",
        "display_name": "HREVN Property Managers Demo",
        "notes": "Demo corporativa con dos propiedades, dos property managers y activos mixtos.",
    }


def _manager_blueprint() -> list[dict[str, Any]]:
    return [
        {
            "manager_id": "manager-salamanca-01",
            "full_name": "Lucía Moreno",
            "email": "lucia.moreno.demo@hrevn.test",
            "role": "Property Manager Madrid",
            "property_ids": ["property-salamanca"],
        },
        {
            "manager_id": "manager-dali-01",
            "full_name": "Jordi Serra",
            "email": "jordi.serra.demo@hrevn.test",
            "role": "Property Manager Barcelona",
            "property_ids": ["property-dali"],
        },
    ]


def _property_blueprint() -> list[dict[str, Any]]:
    return [
        {
            "property_id": "property-salamanca",
            "name": "Edificio Salamanca",
            "code": "ES-01",
            "address_line": "Calle Núñez de Balboa 84",
            "city": "Madrid",
            "notes": "Planta baja con dos locales y tres plantas residenciales.",
        },
        {
            "property_id": "property-dali",
            "name": "Edificio Salvador Dalí",
            "code": "ESD-01",
            "address_line": "Carrer de la Marina 118",
            "city": "Barcelona",
            "notes": "Planta baja con dos locales y cinco plantas residenciales.",
        },
    ]


def _normalize_location(location: dict[str, Any]) -> dict[str, Any]:
    captured_at = str(location.get("captured_at") or "").strip() or _utc_now()
    return {
        "latitude": round(float(location["latitude"]), 7),
        "longitude": round(float(location["longitude"]), 7),
        "accuracy_meters": round(float(location["accuracy_meters"]), 2),
        "captured_at": captured_at,
        "source": "browser_geolocation",
    }


def _default_units() -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []

    units.extend(
        [
            {
                "unit_id": "local-salamanca-1",
                "unit_code": "Local 1",
                "property_id": "property-salamanca",
                "floor_label": "Planta baja",
                "door_label": "Local 1",
                "layout_type": "local_60",
                "asset_type": "local",
                "bedrooms": 0,
                "bathrooms": 1,
                "area_sqm": 60,
                "rental_status": "under_review",
                "has_garage": False,
                "has_storage": False,
            },
            {
                "unit_id": "local-salamanca-2",
                "unit_code": "Local 2",
                "property_id": "property-salamanca",
                "floor_label": "Planta baja",
                "door_label": "Local 2",
                "layout_type": "local_40",
                "asset_type": "local",
                "bedrooms": 0,
                "bathrooms": 1,
                "area_sqm": 40,
                "rental_status": "vacant",
                "has_garage": False,
                "has_storage": False,
            },
        ]
    )

    for floor in range(1, 4):
        units.append(
            {
                "unit_id": f"unit-rmc-{floor}a",
                "unit_code": f"{floor}A",
                "property_id": "property-salamanca",
                "floor_label": f"Planta {floor}",
                "door_label": "A",
                "layout_type": "3d2b",
                "asset_type": "vivienda",
                "bedrooms": 3,
                "bathrooms": 2,
                "garage_number": f"G-{floor}01",
                "storage_number": f"T-{floor}01",
                "rental_status": "rented" if floor == 1 else "entry_pending" if floor == 2 else "under_review",
                "has_garage": True,
                "has_storage": True,
            }
        )
        units.append(
            {
                "unit_id": f"unit-rmc-{floor}b",
                "unit_code": f"{floor}B",
                "property_id": "property-salamanca",
                "floor_label": f"Planta {floor}",
                "door_label": "B",
                "layout_type": "2d1b",
                "asset_type": "vivienda",
                "bedrooms": 2,
                "bathrooms": 1,
                "garage_number": f"G-{floor}02",
                "storage_number": f"T-{floor}02",
                "rental_status": "exit_in_progress" if floor == 1 else "rented" if floor == 2 else "vacant",
                "has_garage": True,
                "has_storage": True,
            }
        )

    units.extend(
        [
            {
                "unit_id": "local-dali-1",
                "unit_code": "Local 1",
                "property_id": "property-dali",
                "floor_label": "Planta baja",
                "door_label": "Local 1",
                "layout_type": "local_60",
                "asset_type": "local",
                "bedrooms": 0,
                "bathrooms": 1,
                "area_sqm": 60,
                "rental_status": "rented",
                "has_garage": False,
                "has_storage": False,
            },
            {
                "unit_id": "local-dali-2",
                "unit_code": "Local 2",
                "property_id": "property-dali",
                "floor_label": "Planta baja",
                "door_label": "Local 2",
                "layout_type": "local_40",
                "asset_type": "local",
                "bedrooms": 0,
                "bathrooms": 1,
                "area_sqm": 40,
                "rental_status": "vacant",
                "has_garage": False,
                "has_storage": False,
            },
        ]
    )

    for floor in range(1, 6):
        units.append(
            {
                "unit_id": f"unit-esd-{floor}a",
                "unit_code": f"{floor}A",
                "property_id": "property-dali",
                "floor_label": f"Planta {floor}",
                "door_label": "A",
                "layout_type": "3d2b",
                "asset_type": "vivienda",
                "bedrooms": 3,
                "bathrooms": 2,
                "garage_number": f"DG-{floor}01",
                "storage_number": f"DT-{floor}01",
                "rental_status": "rented" if floor in (1, 2) else "under_review" if floor == 3 else "entry_pending" if floor == 4 else "vacant",
                "has_garage": True,
                "has_storage": True,
            }
        )
        units.append(
            {
                "unit_id": f"unit-esd-{floor}b",
                "unit_code": f"{floor}B",
                "property_id": "property-dali",
                "floor_label": f"Planta {floor}",
                "door_label": "B",
                "layout_type": "2d1b",
                "asset_type": "vivienda",
                "bedrooms": 2,
                "bathrooms": 1,
                "garage_number": f"DG-{floor}02",
                "storage_number": f"DT-{floor}02",
                "rental_status": "rented" if floor == 1 else "vacant" if floor == 5 else "exit_in_progress" if floor == 2 else "rented",
                "has_garage": True,
                "has_storage": True,
            }
        )

    return units


def _space_blueprint(layout_type: str) -> list[tuple[str, str]]:
    base = [
        ("living_room", "Salón"),
        ("kitchen", "Cocina"),
        ("hallway", "Pasillo"),
        ("laundry", "Lavadero"),
        ("terrace", "Terraza"),
        ("garage", "Garaje"),
        ("storage", "Trastero"),
    ]
    if layout_type == "2d1b":
        return [
            ("bedroom_1", "Dormitorio 1"),
            ("bedroom_2", "Dormitorio 2"),
            ("bathroom_1", "Baño 1"),
            *base,
        ]
    if layout_type.startswith("local_"):
        return [
            ("main_room", "Zona principal"),
            ("storage_area", "Almacén"),
            ("bathroom_1", "Aseo"),
            ("shopfront", "Escaparate y acceso"),
        ]
    return [
        ("bedroom_1", "Dormitorio 1"),
        ("bedroom_2", "Dormitorio 2"),
        ("bedroom_3", "Dormitorio 3"),
        ("bathroom_1", "Baño 1"),
        ("bathroom_2", "Baño 2"),
        *base,
    ]


def _build_spaces(unit_id: str, layout_type: str) -> list[dict[str, Any]]:
    spaces: list[dict[str, Any]] = []
    for index, (space_type, label) in enumerate(_space_blueprint(layout_type), start=1):
        spaces.append(
            {
                "space_id": f"{unit_id}-{space_type}",
                "space_type": space_type,
                "space_label": label,
                "sort_order": index,
            }
        )
    return spaces


def _default_state() -> dict[str, Any]:
    units = _default_units()
    spaces = {unit["unit_id"]: _build_spaces(unit["unit_id"], unit["layout_type"]) for unit in units}
    return {
        "company": _company_blueprint(),
        "managers": _manager_blueprint(),
        "properties": _property_blueprint(),
        "property": {
            "property_id": "property-demo-portfolio",
            "name": "Portfolio property manager demo",
            "code": "PMD-01",
            "address_line": "Madrid y Barcelona",
            "city": "Demo multi-activo",
            "notes": "Demo corporativa con dos edificios, locales, viviendas y property managers asignados.",
        },
        "units": units,
        "spaces": spaces,
        "visits": {},
    }


def _ensure_state() -> dict[str, Any]:
    if not settings.property_demo_enabled:
        raise HTTPException(status_code=404, detail="property_demo_disabled")
    path = _state_path()
    desired = _default_state()
    if not path.exists():
        path.write_text(json.dumps(desired, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return desired
    state = json.loads(path.read_text(encoding="utf-8"))

    state.setdefault("company", desired["company"])
    state.setdefault("managers", desired["managers"])
    state.setdefault("properties", desired["properties"])
    state.setdefault("property", desired["property"])
    state.setdefault("units", [])
    state.setdefault("spaces", {})
    state.setdefault("visits", {})

    if isinstance(state.get("property"), dict):
        if state["property"].get("property_id") == "property-ral-01":
            state["property"] = deepcopy(desired["property"])
        for field, value in desired["property"].items():
            state["property"].setdefault(field, value)

    existing_units = {unit["unit_id"]: unit for unit in state["units"]}
    for desired_unit in desired["units"]:
        if desired_unit["unit_id"] not in existing_units:
            state["units"].append(desired_unit)
            state["spaces"][desired_unit["unit_id"]] = desired["spaces"][desired_unit["unit_id"]]
            continue
        current = existing_units[desired_unit["unit_id"]]
        for field, value in desired_unit.items():
            current.setdefault(field, value)
        state["spaces"].setdefault(desired_unit["unit_id"], desired["spaces"][desired_unit["unit_id"]])

    _save_state(state)
    return state


def _save_state(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _unit_by_id(state: dict[str, Any], unit_id: str) -> dict[str, Any]:
    for unit in state["units"]:
        if unit["unit_id"] == unit_id:
            return unit
    raise HTTPException(status_code=404, detail="property_unit_not_found")


def _property_by_id(state: dict[str, Any], property_id: str) -> dict[str, Any]:
    for property_item in state.get("properties", []):
        if property_item["property_id"] == property_id:
            return property_item
    raise HTTPException(status_code=404, detail="property_not_found")


def _visit_by_id(state: dict[str, Any], visit_id: str) -> dict[str, Any]:
    visit = state["visits"].get(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="property_visit_not_found")
    return visit


def _decorate_photo(visit_id: str, photo: dict[str, Any]) -> dict[str, Any]:
    return {
        **deepcopy(photo),
        "photo_api_path": _photo_api_path(visit_id, photo["photo_id"]),
        "photo_url": _photo_public_url(visit_id, photo["photo_id"]),
    }


def _decorate_visit(visit: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(visit)
    data["photos"] = [_decorate_photo(visit["visit_id"], photo) for photo in visit.get("photos", [])]
    return data


def _space_by_id(state: dict[str, Any], unit_id: str, space_id: str) -> dict[str, Any]:
    for space in state["spaces"].get(unit_id, []):
        if space["space_id"] == space_id:
            return space
    raise HTTPException(status_code=404, detail="property_space_not_found")


def _decorate_unit(state: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    visits = [_decorate_visit(visit) for visit in state["visits"].values() if visit["unit_id"] == unit["unit_id"]]
    visits.sort(key=lambda item: item["created_at"], reverse=True)
    latest_visit = visits[0] if visits else None
    return {
        **deepcopy(unit),
        "property": next((deepcopy(item) for item in state.get("properties", []) if item["property_id"] == unit.get("property_id")), None),
        "spaces": deepcopy(state["spaces"].get(unit["unit_id"], [])),
        "latest_visit": latest_visit,
        "visits": visits,
    }


def get_demo_overview(*, manager_id: str | None = None) -> dict[str, Any]:
    state = _ensure_state()
    managers = deepcopy(state.get("managers", []))
    properties = deepcopy(state.get("properties", []))
    selected_manager = None
    if manager_id:
        selected_manager = next((manager for manager in managers if manager["manager_id"] == manager_id), None)
    if selected_manager is None and managers:
        selected_manager = managers[0]

    property_index = {item["property_id"]: item for item in properties}
    decorated_units = [_decorate_unit(state, unit) for unit in state["units"]]

    portfolio: list[dict[str, Any]] = []
    visible_property_ids = set(selected_manager.get("property_ids", [])) if selected_manager else {item["property_id"] for item in properties}
    for property_id in visible_property_ids:
        property_item = property_index.get(property_id)
        if not property_item:
            continue
        property_assets = [item for item in decorated_units if item.get("property_id") == property_id]
        portfolio.append(
            {
                **property_item,
                "assets": property_assets,
                "stats": {
                    "assets_count": len(property_assets),
                    "visits_count": sum(len(asset.get("visits", [])) for asset in property_assets),
                    "open_visits_count": sum(
                        1 for asset in property_assets for visit in asset.get("visits", []) if visit.get("visit_status") == "draft"
                    ),
                },
            }
        )

    return {
        "company": deepcopy(state.get("company", {})),
        "managers": managers,
        "selected_manager": selected_manager,
        "properties": portfolio,
    }


def get_demo_building() -> dict[str, Any]:
    state = _ensure_state()
    return {
        "property": deepcopy(state["property"]),
        "units": [_decorate_unit(state, unit) for unit in state["units"]],
    }


def get_demo_unit(unit_id: str) -> dict[str, Any]:
    state = _ensure_state()
    unit = _unit_by_id(state, unit_id)
    return {"property": deepcopy(_property_by_id(state, unit["property_id"])), "unit": _decorate_unit(state, unit)}


def get_demo_visit(visit_id: str) -> dict[str, Any]:
    state = _ensure_state()
    visit = _decorate_visit(_visit_by_id(state, visit_id))
    unit = deepcopy(_unit_by_id(state, visit["unit_id"]))
    return {"property": deepcopy(_property_by_id(state, unit["property_id"])), "unit": unit, "visit": visit}


def create_demo_visit(
    *,
    unit_id: str,
    visit_type: str,
    performed_by: str,
    tenant_present: bool,
    location: dict[str, Any],
) -> dict[str, Any]:
    state = _ensure_state()
    unit = _unit_by_id(state, unit_id)
    property_item = _property_by_id(state, unit["property_id"])
    visit_id = f"PV-{_short_hash(unit_id + visit_type + _utc_now())}".upper()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    visit = {
        "visit_id": visit_id,
        "unit_id": unit_id,
        "visit_type": visit_type,
        "visit_status": "draft",
        "performed_at": now.isoformat().replace("+00:00", "Z"),
        "performed_by": performed_by.strip() or "Property manager demo",
        "tenant_present": bool(tenant_present),
        "location": _normalize_location(location),
        "summary": "",
        "closed_at": None,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "auto_close_at": (now + timedelta(minutes=AUTO_CLOSE_MINUTES)).isoformat().replace("+00:00", "Z"),
        "spaces": {
            space["space_id"]: {
                "space_id": space["space_id"],
                "space_label": space["space_label"],
                "general_status": "ok",
                "notes": "",
            }
            for space in state["spaces"][unit_id]
        },
        "findings": [],
        "photos": [],
        "annexes": [],
        "bundle": None,
    }
    state["visits"][visit_id] = visit
    _save_state(state)
    return {"property": deepcopy(property_item), "unit": deepcopy(unit), "visit": deepcopy(visit)}


def update_demo_space_check(*, visit_id: str, space_id: str, general_status: str, notes: str | None) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    if visit["visit_status"] != "draft":
        raise HTTPException(status_code=409, detail="property_visit_already_closed")
    _space_by_id(state, visit["unit_id"], space_id)
    visit["spaces"][space_id] = {
        "space_id": space_id,
        "space_label": visit["spaces"][space_id]["space_label"],
        "general_status": general_status,
        "notes": (notes or "").strip(),
    }
    _save_state(state)
    return deepcopy(visit["spaces"][space_id])


def add_demo_finding(*, visit_id: str, space_id: str, category: str, severity: str, description: str) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    if visit["visit_status"] != "draft":
        raise HTTPException(status_code=409, detail="property_visit_already_closed")
    space = _space_by_id(state, visit["unit_id"], space_id)
    finding = {
        "finding_id": f"F-{uuid4().hex[:10]}".upper(),
        "space_id": space_id,
        "space_label": space["space_label"],
        "category": category.strip() or "other",
        "severity": severity.strip() or "medium",
        "description": description.strip(),
        "created_at": _utc_now(),
    }
    if not finding["description"]:
        raise HTTPException(status_code=400, detail="property_visit_finding_description_required")
    visit["findings"].append(finding)
    _save_state(state)
    return deepcopy(finding)


def delete_demo_finding(*, visit_id: str, finding_id: str) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    if visit["visit_status"] != "draft":
        raise HTTPException(status_code=409, detail="property_visit_already_closed")

    finding = next((item for item in visit["findings"] if item["finding_id"] == finding_id), None)
    if not finding:
        raise HTTPException(status_code=404, detail="property_visit_finding_not_found")

    photos_to_remove = [photo for photo in visit["photos"] if photo.get("finding_id") == finding_id]
    for photo in photos_to_remove:
        target = Path(photo["file_path"])
        if target.exists():
            target.unlink()

    visit["photos"] = [photo for photo in visit["photos"] if photo.get("finding_id") != finding_id]
    visit["findings"] = [item for item in visit["findings"] if item["finding_id"] != finding_id]
    _save_state(state)
    return {
        "finding_id": finding_id,
        "deleted_photos": len(photos_to_remove),
    }


def add_demo_photo(
    *,
    visit_id: str,
    space_id: str,
    finding_id: str | None,
    filename: str,
    media_type: str | None,
    content_base64: str,
) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    if visit["visit_status"] != "draft":
        raise HTTPException(status_code=409, detail="property_visit_already_closed")
    space = _space_by_id(state, visit["unit_id"], space_id)

    payload = content_base64.strip()
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_photo_payload:{exc}") from exc
    if not raw:
        raise HTTPException(status_code=400, detail="empty_photo_payload")

    safe_name = Path(filename.strip() or f"{space_id}.jpg").name
    ext = Path(safe_name).suffix or mimetypes.guess_extension(media_type or "") or ".jpg"
    photo_id = f"P-{uuid4().hex[:10]}".upper()
    visit_dir = _photos_root() / visit_id
    visit_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{photo_id.lower()}-{_slug(Path(safe_name).stem)}{ext}"
    target = visit_dir / stored_name
    target.write_bytes(raw)
    photo_hash = hashlib.sha256(raw).hexdigest()

    photo = {
        "photo_id": photo_id,
        "space_id": space_id,
        "space_label": space["space_label"],
        "finding_id": finding_id,
        "filename": safe_name,
        "media_type": media_type or mimetypes.guess_type(safe_name)[0] or "image/jpeg",
        "file_path": str(target),
        "relative_path": f"photos/{visit_id}/{stored_name}",
        "photo_sha256": photo_hash,
        "captured_at": _utc_now(),
    }
    visit["photos"].append(photo)
    _save_state(state)
    return deepcopy(photo)


def _build_visit_summary_document(state: dict[str, Any], unit: dict[str, Any], visit: dict[str, Any]) -> bytes:
    property_item = _property_by_id(state, unit["property_id"])
    summary = {
        "property": property_item,
        "unit": {
            "unit_id": unit["unit_id"],
            "unit_code": unit["unit_code"],
            "layout_type": unit["layout_type"],
            "asset_type": unit["asset_type"],
            "bedrooms": unit["bedrooms"],
            "bathrooms": unit["bathrooms"],
            "rental_status": unit["rental_status"],
        },
        "visit": {
            "visit_id": visit["visit_id"],
            "visit_type": visit["visit_type"],
            "performed_at": visit["performed_at"],
            "performed_by": visit["performed_by"],
            "tenant_present": visit["tenant_present"],
            "location": visit.get("location"),
            "summary": visit["summary"],
            "closed_at": visit["closed_at"],
        },
        "spaces": list(visit["spaces"].values()),
        "findings": visit["findings"],
        "photos": [
            {
                "photo_id": photo["photo_id"],
                "space_id": photo["space_id"],
                "space_label": photo["space_label"],
                "filename": photo["filename"],
                "media_type": photo["media_type"],
                "photo_sha256": photo["photo_sha256"],
                "captured_at": photo["captured_at"],
            }
            for photo in visit["photos"]
        ],
    }
    return (json.dumps(summary, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def close_demo_visit(*, visit_id: str, summary: str | None) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    if visit["visit_status"] != "draft":
        raise HTTPException(status_code=409, detail="property_visit_already_closed")
    if not visit["photos"]:
        raise HTTPException(status_code=400, detail="property_visit_requires_photos")

    visit["summary"] = (summary or "").strip()
    visit["closed_at"] = _utc_now()
    visit["visit_status"] = "closed"

    unit = _unit_by_id(state, visit["unit_id"])
    property_item = _property_by_id(state, unit["property_id"])
    location = visit.get("location") or {
        "latitude": None,
        "longitude": None,
        "accuracy_meters": None,
        "captured_at": None,
        "source": "not_available",
    }
    document_name = f"{unit['unit_code']}_{visit_id}_visit_summary.json"
    record = {
        "profile": PROPERTY_DEMO_PROFILE,
        "anchor_network": "sepolia",
        "package_title": f"Visita {visit['visit_type']} · {property_item['name']} · Inmueble {unit['unit_code']}",
        "package_summary": "Paquete verificable del estado del inmueble con incidencias y evidencias fotográficas.",
        "issued_by": visit["performed_by"],
        "language": "es",
        "profile_inputs": {
            "property_name": property_item["name"],
            "property_address": f"{property_item['address_line']}, {property_item['city']}",
            "unit_code": unit["unit_code"],
            "asset_type": unit["asset_type"],
            "visit_type": visit["visit_type"],
            "visit_id": visit["visit_id"],
            "performed_at": visit["performed_at"],
            "performed_by": visit["performed_by"],
            "rental_status": unit["rental_status"],
            "geo_latitude": location["latitude"],
            "geo_longitude": location["longitude"],
            "geo_accuracy_meters": location["accuracy_meters"],
            "geo_captured_at": location["captured_at"],
        },
        "documents": [
            {
                "document_id": f"summary-{visit_id}",
                "role": "visit_summary",
                "filename": document_name,
                "media_type": "application/json",
                "label": "Resumen de visita",
                "content": _build_visit_summary_document(state, unit, visit),
            }
        ],
        "images": [
            {
                "artifact_id": photo["photo_id"],
                "role": "space_photo",
                "filename": f"{photo['photo_id'].lower()}-{Path(photo['filename']).name}",
                "media_type": photo["media_type"],
                "label": f"{photo['space_label']} · {photo['filename']}",
                "content": Path(photo["file_path"]).read_bytes(),
            }
            for photo in visit["photos"]
        ],
    }

    created = create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")
    visit["bundle"] = {
        "bundle_id": created["bundle_id"],
        "record_id": created["record_id"],
        "bundle_path": created["bundle_path"],
        "root_hash": created.get("root_hash"),
        "signature_status": created.get("signature_status"),
        "signature_algorithm": created.get("signature_algorithm"),
        "signature_public_key_id": created.get("signature_public_key_id"),
        "anchor_status": created.get("anchor_status"),
        "anchor": created.get("anchor"),
        "verification_url": _visit_verify_url(visit_id),
        "bundle_verification_url": f"{settings.public_site_base_url}/verify/evidence-bundle/?bundle_id={created['bundle_id']}",
        "created_at": _utc_now(),
    }
    _save_state(state)
    return get_demo_visit(visit_id)


def resolve_demo_photo(visit_id: str, photo_id: str) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    for photo in visit.get("photos", []):
        if photo["photo_id"] == photo_id:
            target = Path(photo["file_path"])
            if not target.exists():
                raise HTTPException(status_code=404, detail="property_visit_photo_file_not_found")
            return {
                "path": target,
                "media_type": photo.get("media_type") or mimetypes.guess_type(target.name)[0] or "image/jpeg",
                "filename": photo.get("filename") or target.name,
            }
    raise HTTPException(status_code=404, detail="property_visit_photo_not_found")


def get_public_visit_verify_record(visit_id: str) -> dict[str, Any]:
    state = _ensure_state()
    visit = _visit_by_id(state, visit_id)
    unit = _unit_by_id(state, visit["unit_id"])
    bundle = visit.get("bundle")
    if not bundle:
        raise HTTPException(status_code=404, detail="property_visit_bundle_not_found")
    verification = verify_bundle_source(str(resolve_bundle_download(bundle["bundle_id"])))
    return {
        "property": deepcopy(state["property"]),
        "unit": deepcopy(unit),
        "visit": {
            "visit_id": visit["visit_id"],
            "visit_type": visit["visit_type"],
            "visit_status": visit["visit_status"],
            "performed_at": visit["performed_at"],
            "performed_by": visit["performed_by"],
            "tenant_present": visit["tenant_present"],
            "location": deepcopy(visit.get("location")),
            "summary": visit["summary"],
            "closed_at": visit["closed_at"],
            "spaces_reviewed": len(visit["spaces"]),
            "findings_count": len(visit["findings"]),
            "photos_count": len(visit["photos"]),
            "photos": [_decorate_photo(visit["visit_id"], photo) for photo in visit.get("photos", [])],
        },
        "bundle": deepcopy(bundle),
        "verification": verification,
    }
