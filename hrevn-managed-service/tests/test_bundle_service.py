from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.bundle_service import HTTPException, create_bundle


def _sample_record() -> dict:
    return {
        "agent_name": "Support Classifier",
        "model_version": "claude-sonnet-4-6",
        "task_description": "Classify support tickets",
        "test_environment": "production-staging",
        "issuer_id": "acme-corp",
        "issuer_name": "Acme Corp",
    }


def _sample_eb1_record() -> dict:
    return {
        "profile": "us_contractor_owner_dispute_v1",
        "profile_inputs": {
            "property_address": "4812 W Oak Ridge Dr, Phoenix, AZ 85031",
            "homeowner_name": "Laura Benton",
            "contractor_name": "Oakline Remodel LLC",
            "project_reference": "OR-2026-041",
            "original_budget_amount": 47000,
            "currency": "USD",
            "project_start_date": "2026-03-14",
            "dispute_summary": "Later disputed change order and supporting photo.",
        },
        "package_title": "Original remodel package",
        "package_summary": "Files sealed before the disputed change order.",
        "issued_by": "HREVN sample operator",
        "documents": [
            {
                "role": "contract_scope",
                "filename": "contract_scope_of_work_2026.pdf",
                "content": "contract-scope-v1",
            }
        ],
        "images": [
            {
                "role": "before_photo",
                "filename": "prework_living_room.jpg",
                "content": "living-room-photo-v1",
            }
        ],
        "attachments": [
            {
                "role": "initial_takeoff",
                "filename": "initial_takeoff.xlsx",
                "content": "takeoff-sheet-v1",
            }
        ],
    }


def test_create_bundle_defaults_to_verified_record_mode():
    created = create_bundle(record=_sample_record(), traces=[])

    assert created["bundle_mode"] == "verified_record_v1"
    assert created["bundle_id"].startswith("BND-")


def test_create_bundle_eb1_mode_is_routed_but_not_yet_implemented():
    created = create_bundle(record=_sample_eb1_record(), traces=[], bundle_mode="evidence_bundle_eb1")

    assert created["bundle_mode"] == "evidence_bundle_eb1"
    assert created["bundle_profile"] == "evidence_bundle_eb1_v1"
    assert created["package_type"] == "us_contractor_owner_dispute_bundle"
    assert created["schema_version"] == "hrevn-eb1-v1"
    assert created["anchor_status"] == "anchor_pending"
    assert created["warnings"] == []
    assert created["record_id"].startswith("EB1-")


def test_create_bundle_eb1_requires_profile():
    with pytest.raises(HTTPException) as excinfo:
        create_bundle(record={}, traces=[], bundle_mode="evidence_bundle_eb1")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "profile_required_for_evidence_bundle_eb1"


def test_create_bundle_eb1_rejects_incomplete_profile_contract():
    record = _sample_eb1_record()
    record["profile_inputs"] = {
        "property_address": "4812 W Oak Ridge Dr, Phoenix, AZ 85031",
        "contractor_name": "Oakline Remodel LLC",
    }
    record["images"] = []

    with pytest.raises(HTTPException) as excinfo:
        create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["error_code"] == "profile_contract_incomplete"
    assert excinfo.value.detail["profile"] == "us_contractor_owner_dispute_v1"
    assert "profile_inputs.homeowner_name" in excinfo.value.detail["missing_required_blocks"]
    assert "images" in excinfo.value.detail["missing_required_blocks"]
    assert "warnings" in excinfo.value.detail


def test_create_bundle_eb1_allows_missing_recommended_roles_as_non_blocking_warning():
    record = _sample_eb1_record()
    record["documents"] = [{"filename": "contractor_estimate_v1.pdf", "content": "estimate-v1"}]

    created = create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")

    assert created["bundle_mode"] == "evidence_bundle_eb1"
    assert created["warnings"] == ["recommended_role_missing:documents"]
