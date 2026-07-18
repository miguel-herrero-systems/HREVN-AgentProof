from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.eb1_templates import (
    build_eb1_how_to_verify_text,
    build_eb1_human_files,
    build_eb1_protocol_version_text,
    build_eb1_readme_text,
    build_eb1_verification_text,
)


def _sample_metadata() -> dict:
    return {
        "profile": "us_contractor_owner_dispute_v1",
        "package_title": "Original remodel package",
        "package_summary": "Files sealed before the disputed change order.",
        "issued_by": "HREVN sample operator",
        "issued_at": "2026-05-05T18:30:00Z",
        "language": "en",
    }


def _sample_manifest() -> dict:
    return {
        "bundle_profile": "evidence_bundle_eb1_v1",
        "package_family": "hrevn_evidence_bundle",
        "package_type": "us_contractor_owner_dispute_bundle",
        "title": "Original remodel package",
        "generated_at_utc": "2026-05-05T18:30:00Z",
        "authoritative_files": [
            "documents/contract_scope_of_work_2026.pdf",
            "attachments/initial_takeoff.xlsx",
            "images/prework_living_room.jpg",
        ],
    }


def test_build_eb1_readme_text_includes_package_context_and_scope_limits():
    text = build_eb1_readme_text(_sample_metadata(), _sample_manifest())

    assert "Title: Original remodel package" in text
    assert "Profile: us_contractor_owner_dispute_v1" in text
    assert "Issued at: 2026-05-05T18:30:00Z" in text
    assert "Files sealed before the disputed change order." in text
    assert "does not certify material truth" in text


def test_build_eb1_protocol_version_text_declares_profile_family_and_root_spec():
    text = build_eb1_protocol_version_text(_sample_manifest())

    assert "Bundle profile: evidence_bundle_eb1_v1" in text
    assert "Package family: hrevn_evidence_bundle" in text
    assert "Package type: us_contractor_owner_dispute_bundle" in text
    assert "Root specification: ROOT_SPEC_EB1.txt" in text
    assert "Root algorithm: HREVN_ROOT_EB1_V1" in text


def test_build_eb1_verification_text_includes_signature_and_anchor_status():
    text = build_eb1_verification_text(
        _sample_metadata(),
        _sample_manifest(),
        anchor_status="anchor_pending",
        signature_status="signed",
        signature_algorithm="Ed25519",
        signature_public_key_id="hrevn-eb-ed25519-01",
    )

    assert "Package: Original remodel package" in text
    assert "Profile: us_contractor_owner_dispute_v1" in text
    assert "Authoritative files: 3" in text
    assert "Root spec file: ROOT_SPEC_EB1.txt" in text
    assert "Signature status: signed" in text
    assert "Signature algorithm: Ed25519" in text
    assert "Signature key id: hrevn-eb-ed25519-01" in text
    assert "Blockchain anchor status: anchor_pending" in text


def test_build_eb1_how_to_verify_text_lists_expected_steps():
    text = build_eb1_how_to_verify_text(_sample_metadata(), _sample_manifest())

    assert "1. Open manifest.json and review authoritative_files." in text
    assert "3. Rebuild the EB1 root serialization exactly as described in ROOT_SPEC_EB1.txt." in text
    assert "5. Review SIGNATURE_ED25519.json to confirm the Ed25519 signature over the root hash." in text
    assert "7. Review BLOCKCHAIN_ANCHOR.json to confirm the published anchor status." in text


def test_build_eb1_human_files_returns_all_required_documents():
    files = build_eb1_human_files(
        _sample_metadata(),
        _sample_manifest(),
        anchor_status="anchored",
        signature_status="signed",
        signature_algorithm="Ed25519",
        signature_public_key_id="hrevn-eb-ed25519-01",
    )

    assert set(files) == {
        "README.txt",
        "PROTOCOL_VERSION.txt",
        "VERIFICATION.txt",
        "HOW_TO_VERIFY_THIS_PACKAGE.txt",
    }
    assert "Blockchain anchor status: anchored" in files["VERIFICATION.txt"]
    assert "Signature status: signed" in files["VERIFICATION.txt"]
