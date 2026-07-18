from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WORKSPACE = ROOT.parents[1]

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.bundle_service import create_bundle


CURATED_SAMPLE_ROOT = (
    WORKSPACE
    / "hrevn-site-astro"
    / "public"
    / "assets"
    / "samples"
    / "evidence-bundle-ai"
    / "ai-document-integrity-sample-en-v1"
)
OUTPUT_DIR = ROOT / "storage" / "bundles" / "official_samples"
OUTPUT_ZIP = OUTPUT_DIR / "us_contractor_owner_dispute_v1_backend_sample.zip"
OUTPUT_META = OUTPUT_DIR / "us_contractor_owner_dispute_v1_backend_sample.meta.json"


def _bytes(path: Path) -> bytes:
    return path.read_bytes()


def build_record() -> dict:
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
                "content": _bytes(CURATED_SAMPLE_ROOT / "documents" / "contract_scope_of_work_2026.pdf"),
            },
            {
                "document_id": "estimate-001",
                "role": "estimate",
                "filename": "contractor_estimate_v1.pdf",
                "media_type": "application/pdf",
                "label": "Contractor Estimate v1",
                "content": _bytes(CURATED_SAMPLE_ROOT / "documents" / "contractor_estimate_v1.pdf"),
            },
            {
                "document_id": "plan-001",
                "role": "floor_plan",
                "filename": "existing_floor_plan.pdf",
                "media_type": "application/pdf",
                "label": "Existing Floor Plan",
                "content": _bytes(CURATED_SAMPLE_ROOT / "documents" / "existing_floor_plan.pdf"),
            },
        ],
        "images": [
            {
                "artifact_id": "img-001",
                "role": "before_photo",
                "filename": "prework_living_room.jpg",
                "media_type": "image/jpeg",
                "content": _bytes(CURATED_SAMPLE_ROOT / "images" / "prework_living_room.jpg"),
            },
            {
                "artifact_id": "img-002",
                "role": "before_photo",
                "filename": "prework_kitchen.jpg",
                "media_type": "image/jpeg",
                "content": _bytes(CURATED_SAMPLE_ROOT / "images" / "prework_kitchen.jpg"),
            },
            {
                "artifact_id": "img-003",
                "role": "before_photo",
                "filename": "prework_bathroom.jpg",
                "media_type": "image/jpeg",
                "content": _bytes(CURATED_SAMPLE_ROOT / "images" / "prework_bathroom.jpg"),
            },
        ],
        "attachments": [
            {
                "document_id": "takeoff-001",
                "role": "initial_takeoff",
                "filename": "initial_takeoff.xlsx",
                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "content": _bytes(CURATED_SAMPLE_ROOT / "attachments" / "initial_takeoff.xlsx"),
            },
            {
                "document_id": "delivery-001",
                "role": "delivery_screenshot",
                "filename": "whatsapp_measurements_capture.png",
                "media_type": "image/png",
                "content": _bytes(CURATED_SAMPLE_ROOT / "attachments" / "whatsapp_measurements_capture.png"),
            },
        ],
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    created = create_bundle(record=build_record(), traces=[], bundle_mode="evidence_bundle_eb1")

    created_path = Path(created["bundle_path"])
    shutil.copy2(created_path, OUTPUT_ZIP)

    meta = {
        "source_bundle_id": created["bundle_id"],
        "source_bundle_path": str(created_path),
        "official_sample_path": str(OUTPUT_ZIP),
        "bundle_mode": created.get("bundle_mode"),
        "bundle_profile": created.get("bundle_profile"),
        "package_type": created.get("package_type"),
        "record_id": created.get("record_id"),
        "schema_version": created.get("schema_version"),
        "issued_at": created.get("issued_at"),
        "expires_at": created.get("expires_at"),
        "root_hash": created.get("root_hash"),
        "anchor_status": created.get("anchor_status"),
        "warnings": created.get("warnings", []),
    }
    OUTPUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
