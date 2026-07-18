from __future__ import annotations

from typing import Any


US_CONTRACTOR_OWNER_DISPUTE_V1 = "us_contractor_owner_dispute_v1"
PROPERTY_MANAGER_RENTAL_VISIT_V1 = "property_manager_rental_visit_v1"
JUNTA_ANDALUCIA_PROPERTY_EVENT_V1 = "junta_andalucia_property_event_v1"
PROMOTORA_CONSTRUCTION_CERTIFICATE_V1 = "promotora_construction_certificate_v1"
PROMOTORA_HANDOVER_REVIEW_V1 = "promotora_handover_review_v1"


PROFILE_CONTRACTS: dict[str, dict[str, Any]] = {
    US_CONTRACTOR_OWNER_DISPUTE_V1: {
        "required_profile_inputs": [
            "property_address",
            "homeowner_name",
            "contractor_name",
            "project_reference",
            "original_budget_amount",
            "currency",
            "project_start_date",
            "dispute_summary",
        ],
        "required_file_groups": {
            "documents": 1,
            "images": 1,
            "attachments": 1,
        },
        "recommended_roles": {
            "documents": ["contract_scope", "estimate"],
            "images": ["before_photo"],
            "attachments": ["initial_takeoff"],
        },
    },
    PROPERTY_MANAGER_RENTAL_VISIT_V1: {
        "required_profile_inputs": [
            "property_name",
            "property_address",
            "unit_code",
            "visit_type",
            "visit_id",
            "performed_at",
            "performed_by",
            "rental_status",
        ],
        "required_file_groups": {
            "documents": 1,
            "images": 1,
            "attachments": 0,
        },
        "recommended_roles": {
            "documents": ["visit_summary"],
            "images": ["space_photo"],
            "attachments": [],
        },
    },
    JUNTA_ANDALUCIA_PROPERTY_EVENT_V1: {
        "required_profile_inputs": [
            "building_name",
            "building_address",
            "asset_code",
            "event_type",
            "event_id",
            "performed_at",
            "performed_by",
            "photo_reference",
        ],
        "required_file_groups": {
            "documents": 1,
            "images": 1,
            "attachments": 0,
        },
        "recommended_roles": {
            "documents": ["event_summary"],
            "images": ["event_photo"],
            "attachments": [],
        },
    },
    PROMOTORA_CONSTRUCTION_CERTIFICATE_V1: {
        "required_profile_inputs": [
            "promotion_name",
            "location",
            "period",
            "global_progress_pct",
            "certified_at",
            "certified_by",
        ],
        "required_file_groups": {
            "documents": 1,
            "images": 1,
            "attachments": 0,
        },
        "recommended_roles": {
            "documents": ["construction_certificate_report"],
            "images": ["construction_site_photo"],
            "attachments": [],
        },
    },
    PROMOTORA_HANDOVER_REVIEW_V1: {
        "required_profile_inputs": [
            "promotion_name",
            "unit",
            "client",
            "reviewed_at",
            "reviewed_by",
        ],
        "required_file_groups": {
            "documents": 1,
            "images": 1,
            "attachments": 0,
        },
        "recommended_roles": {
            "documents": ["handover_review_report"],
            "images": ["handover_defect_photo"],
            "attachments": [],
        },
    },
}


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _roles(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    roles: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            role = item.get("role")
            if isinstance(role, str) and role.strip():
                roles.add(role.strip())
    return roles


def validate_profile_contract(profile: str, record: dict[str, Any]) -> dict[str, Any]:
    contract = PROFILE_CONTRACTS.get(profile)
    if not contract:
        return {
            "known_profile": False,
            "missing_required_blocks": [],
            "warnings": [f"unknown_profile:{profile}"],
            "details": {},
        }

    missing_required_blocks: list[str] = []
    warnings: list[str] = []

    profile_inputs = record.get("profile_inputs")
    if not isinstance(profile_inputs, dict):
        profile_inputs = {}

    for field in contract["required_profile_inputs"]:
        if not _present(profile_inputs.get(field)):
            missing_required_blocks.append(f"profile_inputs.{field}")

    for group_name, minimum in contract["required_file_groups"].items():
        items = record.get(group_name)
        count = len(items) if isinstance(items, list) else 0
        if count < minimum:
            missing_required_blocks.append(group_name)

    recommended_roles_present: dict[str, list[str]] = {}
    for group_name, expected_roles in contract["recommended_roles"].items():
        present = sorted(_roles(record.get(group_name)))
        recommended_roles_present[group_name] = present
        if not set(expected_roles).intersection(present):
            warnings.append(f"recommended_role_missing:{group_name}")

    validation_status = "profile_inputs_incomplete" if missing_required_blocks else "profile_contract_ok"

    return {
        "known_profile": True,
        "missing_required_blocks": missing_required_blocks,
        "warnings": warnings,
        "validation_status": validation_status,
        "details": {
            "required_profile_inputs": contract["required_profile_inputs"],
            "required_file_groups": contract["required_file_groups"],
            "recommended_roles": contract["recommended_roles"],
            "present_roles": recommended_roles_present,
        },
    }
