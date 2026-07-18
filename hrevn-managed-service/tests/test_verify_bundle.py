from __future__ import annotations

import sys
from pathlib import Path
import base64


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.bundle_service import create_bundle, verify_bundle_source
from hrevn_managed_service.config import settings
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


PLUGIN_DEMO_ROOT = (settings.verifier_plugin_root / "demo").resolve()
VALID_BUNDLE = PLUGIN_DEMO_ROOT / "CAR-2026-002_valid.zip"
TAMPERED_BUNDLE = PLUGIN_DEMO_ROOT / "CAR-2026-002_tampered.zip"
ANCHORED_BUNDLE = PLUGIN_DEMO_ROOT / "CAR-2026-003_anchored.zip"
WORKSPACE_ROOT = ROOT.parents[1]
CURATED_EB1_BUNDLE = (
    WORKSPACE_ROOT
    / "hrevn-site-astro"
    / "public"
    / "assets"
    / "samples"
    / "evidence-bundle-ai"
    / "hrevn-evidence-bundle-ai-sample-v2.zip"
)


def _sample_record() -> dict:
    return {
        "agent_name": "Support Classifier",
        "model_version": "claude-sonnet-4-6",
        "task_description": "Classify support tickets",
        "test_environment": "production-staging",
        "issuer_id": "acme-corp",
        "issuer_name": "Acme Corp",
        "issuer_type": "organizational_issuer",
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
        "language": "en",
        "sample_only": True,
        "documents": [
            {
                "document_id": "contract-001",
                "role": "contract_scope",
                "filename": "contract_scope_of_work_2026.pdf",
                "media_type": "application/pdf",
                "content": b"%PDF-contract-scope%",
            },
            {
                "document_id": "estimate-001",
                "role": "estimate",
                "filename": "contractor_estimate_v1.pdf",
                "media_type": "application/pdf",
                "content": b"%PDF-estimate%",
            },
        ],
        "images": [
            {
                "artifact_id": "img-001",
                "role": "before_photo",
                "filename": "prework_living_room.jpg",
                "media_type": "image/jpeg",
                "content": b"binary-photo-placeholder",
            }
        ],
        "attachments": [
            {
                "document_id": "takeoff-001",
                "role": "initial_takeoff",
                "filename": "initial_takeoff.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content": b"xlsx-placeholder",
            }
        ],
    }


def _set_setting(name: str, value):
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    return original


def test_verify_bundle_valid_demo():
    result = verify_bundle_source(str(VALID_BUNDLE))

    assert result["tool"] == "verify_bundle"
    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert result["errors"] == []
    assert result["aer_id"] == "AER-CAR-2026-002"


def test_verify_bundle_tampered_demo():
    result = verify_bundle_source(str(TAMPERED_BUNDLE))

    assert result["tool"] == "verify_bundle"
    assert result["valid"] is False
    assert any("checksum_mismatch" in error or "root_hash_mismatch" in error for error in result["errors"])


def test_verify_bundle_anchored_demo():
    result = verify_bundle_source(str(ANCHORED_BUNDLE))

    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert "not_anchored" not in " ".join(result["warnings"])


def test_verify_bundle_generated_bundle_is_compatible_with_legacy_verifier():
    created = create_bundle(record=_sample_record(), traces=_sample_traces())

    result = verify_bundle_source(created["bundle_path"])

    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert result["artifact_count"] == 5
    assert result["schema_version"] == "hrevn-aer-v0.3.3"


def test_verify_bundle_curated_eb1_sample_is_valid():
    result = verify_bundle_source(str(CURATED_EB1_BUNDLE))

    assert result["tool"] == "verify_bundle"
    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert result["artifact_count"] == 14
    assert result["schema_version"] == "evidence_bundle_ai_document_integrity_v1"
    assert "root_hash_mismatch: computed hash does not match declared" not in result["errors"]


def test_verify_bundle_backend_eb1_sample_is_valid():
    created = create_bundle(record=_sample_eb1_record(), traces=[], bundle_mode="evidence_bundle_eb1")
    result = verify_bundle_source(created["bundle_path"])

    assert result["tool"] == "verify_bundle"
    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert result["artifact_count"] == 4
    assert result["schema_version"] == "evidence_bundle_eb1_v1"
    assert result["aer_id"].startswith("EB1-")
    assert result["anchor"]["status"] == "anchor_pending"
    assert result["anchor"]["network"] == "base"
    assert "anchor_pending" in result["warnings"]
    assert result["signature_status"] == "signing_not_configured"
    assert "signature_not_configured" in result["warnings"]


def test_verify_bundle_backend_eb1_signed_bundle_reports_valid_signature():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_key_b64 = base64.b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_key_b64 = base64.b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    original_private = _set_setting("hrevn_eb_signing_private_key", private_key_b64)
    original_public = _set_setting("hrevn_eb_signing_public_key", public_key_b64)
    original_key_id = _set_setting("hrevn_eb_signing_public_key_id", "hrevn-eb-ed25519-test")
    try:
        created = create_bundle(record=_sample_eb1_record(), traces=[], bundle_mode="evidence_bundle_eb1")
        result = verify_bundle_source(created["bundle_path"])
    finally:
        object.__setattr__(settings, "hrevn_eb_signing_private_key", original_private)
        object.__setattr__(settings, "hrevn_eb_signing_public_key", original_public)
        object.__setattr__(settings, "hrevn_eb_signing_public_key_id", original_key_id)

    assert result["valid"] is True
    assert result["root_hash_match"] is True
    assert result["signature_status"] == "signed"
    assert result["signature_valid"] is True
    assert result["signature_algorithm"] == "Ed25519"
    assert result["signature_public_key_id"] == "hrevn-eb-ed25519-test"
    assert result["anchor"]["status"] == "anchor_pending"
    assert "signature_invalid" not in result["warnings"]
