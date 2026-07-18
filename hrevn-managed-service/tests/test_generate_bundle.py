from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.bundle_service import create_bundle, resolve_bundle_download


def _sample_record() -> dict:
    return {
        "agent_name": "Support Classifier",
        "model_version": "claude-sonnet-4-6",
        "task_description": "Classify support tickets",
        "test_environment": "production-staging",
        "issuer_id": "acme-corp",
        "issuer_name": "Acme Corp",
        "issuer_type": "organizational_issuer",
        "integration_profile": "ai_review_verified_record_v1",
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
        "package_title": "Original remodel package at project start",
        "package_summary": "Residential remodel documentation sealed before the dispute.",
        "issued_by": "HREVN sample operator",
        "input_notes": "Base package input plus vertical overlay for contractor-owner disputes.",
        "documents": [
            {
                "document_id": "contract-scope-001",
                "role": "contract_scope",
                "filename": "contract_scope_of_work_2026.pdf",
                "mime_type": "application/pdf",
            },
            "contractor_estimate_v1.pdf",
        ],
        "images": [
            {
                "document_id": "prework-photo-001",
                "role": "before_photo",
                "filename": "prework_living_room.jpg",
                "mime_type": "image/jpeg",
            }
        ],
        "attachments": [
            {
                "document_id": "takeoff-001",
                "role": "initial_takeoff",
                "filename": "initial_takeoff.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        ],
        "other_files": ["delivery_notes.txt"],
        "case_reference": {
            "case_id": "HREVN-AI-000123",
            "product": "ai_review",
            "client_name": "Empresa X",
            "title": "Triaje de cumplimiento IA",
            "description": "Evaluación inicial del uso de IA",
        },
        "certified_deliverables": [
            {
                "document_id": "deliverable-intake-json",
                "role": "intake_json",
                "type": "application/json",
                "filename": "HREVN_INTAKE_CASE.json",
                "sha256": "abc123",
                "size_bytes": 48211,
                "generated_at": "2026-05-02T09:20:00Z",
                "delivery_status": "deliverable",
                "included_in_zip": False,
            },
            {
                "document_id": "deliverable-final-report-pdf",
                "role": "final_report_pdf",
                "type": "application/pdf",
                "filename": "informe_final_hrevn.pdf",
                "sha256": "def456",
                "size_bytes": 294221,
                "generated_at": "2026-05-02T09:22:00Z",
                "delivery_status": "deliverable",
                "included_in_zip": False,
            },
        ],
    }


def _sample_traces() -> list[dict]:
    return [
        {
            "test_id": "TC-001",
            "result": "PASS",
            "confidence": "high",
            "duration_ms": 220,
            "tokens_used": 430,
            "input_text": "Classify: server down",
            "validator_notes": ["Completed normally"],
        }
    ]


def test_create_bundle_writes_minimum_bundle_and_download_path_resolves():
    created = create_bundle(record=_sample_record(), traces=_sample_traces())

    assert created["bundle_id"].startswith("BND-")
    assert created["record_id"].startswith("AER-")
    assert created["schema_version"] == "hrevn-aer-v0.3.3"

    bundle_path = Path(created["bundle_path"])
    assert bundle_path.exists()
    assert resolve_bundle_download(created["bundle_id"]) == bundle_path

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        assert names == {
            "payload.json",
            "issuance.json",
            "manifest.json",
            "CHECKSUMS.sha256",
            "ROOT_HASH_SHA256.txt",
        }

        payload = json.loads(zf.read("payload.json").decode("utf-8"))
        issuance = json.loads(zf.read("issuance.json").decode("utf-8"))
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))

        assert payload["schema_version"] == "hrevn-aer-v0.3.3"
        assert payload["issuer"]["id"] == "acme-corp"
        assert payload["integration_profile"] == "ai_review_verified_record_v1"
        assert payload["case_reference"]["case_id"] == "HREVN-AI-000123"
        assert payload["profile"] == "us_contractor_owner_dispute_v1"
        assert payload["profile_inputs"]["contractor_name"] == "Oakline Remodel LLC"
        assert payload["package_input"]["title"] == "Original remodel package at project start"
        assert payload["package_input"]["summary"] == "Residential remodel documentation sealed before the dispute."
        assert payload["package_input"]["issued_by"] == "HREVN sample operator"
        assert payload["package_input"]["notes"] == "Base package input plus vertical overlay for contractor-owner disputes."
        assert payload["package_input"]["documents"][0]["role"] == "contract_scope"
        assert payload["package_input"]["documents"][1]["name"] == "contractor_estimate_v1.pdf"
        assert payload["package_input"]["images"][0]["filename"] == "prework_living_room.jpg"
        assert payload["package_input"]["attachments"][0]["role"] == "initial_takeoff"
        assert payload["package_input"]["other_files"][0]["name"] == "delivery_notes.txt"
        assert len(payload["certified_deliverables"]) == 2
        assert payload["certified_deliverables"][1]["role"] == "final_report_pdf"
        assert issuance["signed_payload_hash"] == payload["payload_hash"]
        assert manifest["bundle_profile"] == "managed_generated_aer_v1"
        assert manifest["verification_model"] == "ROOT_AER_V1"
        assert manifest["signature_status"] == "unsigned"
        assert manifest["external_anchor_status"] == "not_anchored"
