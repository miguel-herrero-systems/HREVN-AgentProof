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
                "label": "Contract + Scope of Work",
                "content": "%PDF-contract-scope%",
            }
        ],
        "images": [
            {
                "artifact_id": "img-001",
                "role": "before_photo",
                "filename": "prework_living_room.jpg",
                "media_type": "image/jpeg",
                "content": "binary-photo-placeholder",
            }
        ],
        "attachments": [
            {
                "role": "initial_takeoff",
                "filename": "initial_takeoff.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content": "xlsx-placeholder",
            }
        ],
    }


def test_create_bundle_writes_eb1_bundle_and_download_path_resolves():
    created = create_bundle(record=_sample_eb1_record(), traces=[], bundle_mode="evidence_bundle_eb1")

    assert created["bundle_id"].startswith("BND-")
    assert created["record_id"].startswith("EB1-")
    assert created["schema_version"] == "hrevn-eb1-v1"
    assert created["bundle_profile"] == "evidence_bundle_eb1_v1"
    assert created["package_type"] == "us_contractor_owner_dispute_bundle"
    assert created["anchor_status"] == "anchor_pending"
    assert created["anchor"]["status"] == "anchor_pending"
    assert created["anchor"]["network"] == "base"
    assert created["signature_status"] == "signing_not_configured"

    bundle_path = Path(created["bundle_path"])
    assert bundle_path.exists()
    assert resolve_bundle_download(created["bundle_id"]) == bundle_path

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        assert names == {
            "manifest.json",
            "bundle-metadata.json",
            "CHECKSUMS.sha256",
            "ROOT_HASH_SHA256.txt",
            "ROOT_SPEC_EB1.txt",
            "SIGNATURE_ED25519.json",
            "PROTOCOL_VERSION.txt",
            "VERIFICATION.txt",
            "HOW_TO_VERIFY_THIS_PACKAGE.txt",
            "README.txt",
            "BLOCKCHAIN_ANCHOR.json",
            "documents/contract_scope_of_work_2026.pdf",
            "images/prework_living_room.jpg",
            "attachments/initial_takeoff.xlsx",
        }

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        metadata = json.loads(zf.read("bundle-metadata.json").decode("utf-8"))
        anchor = json.loads(zf.read("BLOCKCHAIN_ANCHOR.json").decode("utf-8"))
        signature = json.loads(zf.read("SIGNATURE_ED25519.json").decode("utf-8"))
        verification = zf.read("VERIFICATION.txt").decode("utf-8")
        readme = zf.read("README.txt").decode("utf-8")
        checksums = zf.read("CHECKSUMS.sha256").decode("utf-8")
        root_hash = zf.read("ROOT_HASH_SHA256.txt").decode("utf-8")

        assert manifest["bundle_profile"] == "evidence_bundle_eb1_v1"
        assert manifest["package_type"] == "us_contractor_owner_dispute_bundle"
        assert manifest["artifact_count"] == 3
        assert manifest["authoritative_files"] == [
            "documents/contract_scope_of_work_2026.pdf",
            "images/prework_living_room.jpg",
            "attachments/initial_takeoff.xlsx",
        ]
        assert manifest["external_anchor_status"] == "anchor_pending"
        assert manifest["signature_status"] == "signing_not_configured"
        assert manifest["signature_artifact"] == "SIGNATURE_ED25519.json"

        assert metadata["profile"] == "us_contractor_owner_dispute_v1"
        assert metadata["package_title"] == "Original remodel package"
        assert metadata["sample_only"] is True

        assert anchor["status"] == "anchor_pending"
        assert anchor["root_hash"] == root_hash
        assert anchor["transaction_reference"] is None
        assert signature["status"] == "signing_not_configured"
        assert signature["root_hash"] == root_hash

        assert "Blockchain anchor status: anchor_pending" in verification
        assert "Signature status: signing_not_configured" in verification
        assert "Title: Original remodel package" in readme
        assert "CHECKSUMS.sha256" not in checksums
        assert "documents/contract_scope_of_work_2026.pdf" in checksums
