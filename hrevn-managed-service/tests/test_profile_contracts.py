from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.profile_contracts import (
    US_CONTRACTOR_OWNER_DISPUTE_V1,
    validate_profile_contract,
)


def test_validate_profile_contract_accepts_complete_us_contractor_profile():
    record = {
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
        "documents": [
            {"role": "contract_scope", "filename": "contract_scope_of_work_2026.pdf"},
            {"role": "estimate", "filename": "contractor_estimate_v1.pdf"},
        ],
        "images": [
            {"role": "before_photo", "filename": "prework_living_room.jpg"},
        ],
        "attachments": [
            {"role": "initial_takeoff", "filename": "initial_takeoff.xlsx"},
        ],
    }

    result = validate_profile_contract(US_CONTRACTOR_OWNER_DISPUTE_V1, record)

    assert result["known_profile"] is True
    assert result["missing_required_blocks"] == []
    assert result["warnings"] == []
    assert result["validation_status"] == "profile_contract_ok"
    assert result["details"]["present_roles"]["documents"] == ["contract_scope", "estimate"]


def test_validate_profile_contract_reports_missing_fields_and_groups():
    record = {
        "profile_inputs": {
            "property_address": "4812 W Oak Ridge Dr, Phoenix, AZ 85031",
            "contractor_name": "Oakline Remodel LLC",
            "currency": "USD",
        },
        "documents": [{"filename": "contractor_estimate_v1.pdf"}],
        "images": [],
        "attachments": [],
    }

    result = validate_profile_contract(US_CONTRACTOR_OWNER_DISPUTE_V1, record)

    assert result["known_profile"] is True
    assert "profile_inputs.homeowner_name" in result["missing_required_blocks"]
    assert "profile_inputs.project_reference" in result["missing_required_blocks"]
    assert "images" in result["missing_required_blocks"]
    assert "attachments" in result["missing_required_blocks"]
    assert "recommended_role_missing:documents" in result["warnings"]
    assert result["validation_status"] == "profile_inputs_incomplete"
