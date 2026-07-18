from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.adapters.generator_adapter import (
    build_eb1_checksums,
    build_eb1_bundle_metadata,
    build_eb1_manifest,
    build_eb1_root_hash,
    build_eb1_root_spec_text,
    normalize_eb1_input_files,
)


def test_normalize_eb1_input_files_builds_deterministic_paths_and_metadata():
    record = {
        "documents": [
            {
                "document_id": "contract-001",
                "filename": "nested/contract_scope_of_work_2026.pdf",
                "mime_type": "application/pdf",
                "role": "contract_scope",
                "label": "Contract scope",
                "description": "Signed scope of work.",
                "content": "doc-bytes-placeholder",
            },
            "contractor_estimate_v1.pdf",
        ],
        "images": [
            {
                "artifact_id": "img-001",
                "filename": "prework_living_room.jpg",
                "media_type": "image/jpeg",
                "role": "before_photo",
            }
        ],
        "attachments": [
            {
                "filename": "initial_takeoff.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "role": "initial_takeoff",
                "authoritative": False,
            }
        ],
        "other_files": ["notes/readme.txt"],
    }

    normalized = normalize_eb1_input_files(record)

    assert [item["relative_path"] for item in normalized] == [
        "documents/contract_scope_of_work_2026.pdf",
        "documents/contractor_estimate_v1.pdf",
        "images/prework_living_room.jpg",
        "attachments/initial_takeoff.xlsx",
        "other_files/readme.txt",
    ]

    assert normalized[0]["source_group"] == "documents"
    assert normalized[0]["source_id"] == "contract-001"
    assert normalized[0]["media_type"] == "application/pdf"
    assert normalized[0]["role"] == "contract_scope"
    assert normalized[0]["label"] == "Contract scope"
    assert normalized[0]["description"] == "Signed scope of work."
    assert normalized[0]["authoritative"] is True
    assert normalized[0]["content"] == "doc-bytes-placeholder"

    assert normalized[1]["source_id"] == "documents-002"
    assert normalized[1]["media_type"] is None
    assert normalized[1]["authoritative"] is True

    assert normalized[2]["source_group"] == "images"
    assert normalized[2]["source_id"] == "img-001"
    assert normalized[2]["role"] == "before_photo"

    assert normalized[3]["source_group"] == "attachments"
    assert normalized[3]["authoritative"] is False

    assert normalized[4]["source_group"] == "other_files"
    assert normalized[4]["filename"] == "readme.txt"


def test_normalize_eb1_input_files_rejects_items_without_filename():
    with pytest.raises(ValueError) as excinfo:
        normalize_eb1_input_files({"documents": [{"role": "contract_scope"}]})

    assert str(excinfo.value) == "missing_filename:documents:1"


def test_build_eb1_bundle_metadata_uses_record_fields_and_defaults():
    metadata = build_eb1_bundle_metadata(
        {
            "profile": "us_contractor_owner_dispute_v1",
            "profile_inputs": {"contractor_name": "Oakline Remodel LLC"},
            "package_title": "Original remodel package",
            "package_summary": "Package delivered before dispute.",
            "issued_by": "HREVN sample operator",
            "issued_at": "2026-05-05T18:30:00Z",
            "sample_only": True,
            "language": "en",
            "input_notes": "Files sealed at project start.",
        },
        issued_at="2026-05-05T19:00:00Z",
    )

    assert metadata == {
        "profile": "us_contractor_owner_dispute_v1",
        "profile_inputs": {"contractor_name": "Oakline Remodel LLC"},
        "package_title": "Original remodel package",
        "package_summary": "Package delivered before dispute.",
        "issued_by": "HREVN sample operator",
        "issued_at": "2026-05-05T18:30:00Z",
        "sample_only": True,
        "language": "en",
        "input_notes": "Files sealed at project start.",
    }


def test_build_eb1_manifest_is_consistent_for_contractor_profile():
    record = {
        "profile": "us_contractor_owner_dispute_v1",
        "package_title": "Original remodel package",
        "language": "en",
        "input_notes": "Files sealed before the disputed change order.",
    }
    normalized = normalize_eb1_input_files(
        {
            "documents": [
                {
                    "document_id": "contract-001",
                    "filename": "contract_scope_of_work_2026.pdf",
                    "media_type": "application/pdf",
                    "role": "contract_scope",
                    "label": "Contract + Scope of Work",
                }
            ],
            "images": [
                {
                    "artifact_id": "img-001",
                    "filename": "prework_living_room.jpg",
                    "media_type": "image/jpeg",
                    "role": "before_photo",
                }
            ],
            "attachments": [
                {
                    "filename": "initial_takeoff.xlsx",
                    "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "role": "initial_takeoff",
                    "description": "Original takeoff sheet.",
                }
            ],
            "other_files": [{"filename": "non_authoritative_note.txt", "authoritative": False}],
        }
    )

    manifest = build_eb1_manifest(record, normalized, generated_at_utc="2026-05-05T18:30:00Z")

    assert manifest["bundle_profile"] == "evidence_bundle_eb1_v1"
    assert manifest["package_family"] == "hrevn_evidence_bundle"
    assert manifest["package_type"] == "us_contractor_owner_dispute_bundle"
    assert manifest["title"] == "Original remodel package"
    assert manifest["language"] == "en"
    assert manifest["generated_at_utc"] == "2026-05-05T18:30:00Z"
    assert manifest["artifact_count"] == 4
    assert len(manifest["artifacts"]) == 4
    assert manifest["authoritative_files"] == [
        "documents/contract_scope_of_work_2026.pdf",
        "images/prework_living_room.jpg",
        "attachments/initial_takeoff.xlsx",
    ]
    assert manifest["root_hash_algorithm"] == "HREVN_ROOT_EB1_V1"
    assert manifest["root_hash_scope"] == "manifest.authoritative_files"
    assert manifest["root_hash_spec_file"] == "ROOT_SPEC_EB1.txt"
    assert manifest["notes"] == ["Files sealed before the disputed change order."]
    assert manifest["artifacts"][0]["artifact_id"] == "contract-001"
    assert manifest["artifacts"][0]["label"] == "Contract + Scope of Work"
    assert manifest["artifacts"][2]["description"] == "Original takeoff sheet."
    assert manifest["artifacts"][3]["authoritative"] is False


def test_build_eb1_manifest_uses_generic_package_type_without_known_profile():
    normalized = normalize_eb1_input_files({"documents": ["generic.pdf"]})

    manifest = build_eb1_manifest({}, normalized, generated_at_utc="2026-05-05T18:30:00Z")

    assert manifest["package_type"] == "generic_evidence_bundle"
    assert manifest["title"] == "HREVN Evidence Bundle"
    assert manifest["language"] == "en"


def test_build_eb1_root_spec_text_is_explicit_and_stable():
    spec = build_eb1_root_spec_text()

    assert spec.startswith("HREVN_ROOT_EB1_V1\n")
    assert "scope=manifest.authoritative_files" in spec
    assert "line_format=relative_path:sha256hex" in spec
    assert "sort=ascending_ascii_by_relative_path" in spec
    assert spec.endswith("encoding=utf-8\n")


def test_build_eb1_root_hash_is_reproducible_from_authoritative_files():
    file_bytes = {
        "documents/contract_scope_of_work_2026.pdf": b"contract-v1",
        "attachments/initial_takeoff.xlsx": b"takeoff-v1",
        "images/prework_living_room.jpg": b"photo-v1",
        "README.txt": b"human-readable-note",
    }
    authoritative_files = [
        "documents/contract_scope_of_work_2026.pdf",
        "images/prework_living_room.jpg",
        "attachments/initial_takeoff.xlsx",
    ]

    root_hash = build_eb1_root_hash(file_bytes, authoritative_files)

    expected_serialized = "\n".join(
        [
            f"attachments/initial_takeoff.xlsx:{hashlib.sha256(b'takeoff-v1').hexdigest()}",
            f"documents/contract_scope_of_work_2026.pdf:{hashlib.sha256(b'contract-v1').hexdigest()}",
            f"images/prework_living_room.jpg:{hashlib.sha256(b'photo-v1').hexdigest()}",
        ]
    )
    assert root_hash == hashlib.sha256(expected_serialized.encode("utf-8")).hexdigest()
    assert root_hash == build_eb1_root_hash(file_bytes, list(reversed(authoritative_files)))


def test_build_eb1_root_hash_requires_all_authoritative_files():
    with pytest.raises(ValueError) as excinfo:
        build_eb1_root_hash(
            {"documents/contract_scope_of_work_2026.pdf": b"contract-v1"},
            [
                "documents/contract_scope_of_work_2026.pdf",
                "images/prework_living_room.jpg",
            ],
        )

    assert str(excinfo.value) == "missing_authoritative_files:images/prework_living_room.jpg"


def test_build_eb1_checksums_excludes_self_and_is_sorted():
    manifest_bytes = b'{"x":1}'
    checksums = build_eb1_checksums(
        {
            "ROOT_HASH_SHA256.txt": b"root-hash",
            "manifest.json": manifest_bytes,
            "CHECKSUMS.sha256": b"should-not-include-self",
            "documents/contract_scope_of_work_2026.pdf": b"contract-v1",
        }
    )

    assert "CHECKSUMS.sha256" not in checksums
    assert checksums.splitlines() == [
        f"{hashlib.sha256(b'root-hash').hexdigest()}  ROOT_HASH_SHA256.txt",
        f"{hashlib.sha256(b'contract-v1').hexdigest()}  documents/contract_scope_of_work_2026.pdf",
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json",
    ]
