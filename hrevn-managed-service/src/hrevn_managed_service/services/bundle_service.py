from __future__ import annotations

try:
    from fastapi import HTTPException
except ModuleNotFoundError:
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

from ..adapters.generator_adapter import (
    generate_evidence_bundle_eb1,
    generate_verified_record_bundle,
    new_bundle_id,
)
from ..services.profile_contracts import validate_profile_contract
from ..adapters.verifier_adapter import run_verify_bundle
from ..services.storage import bundle_path, bundles_dir


def verify_bundle_source(source: str) -> dict:
    return run_verify_bundle(source)


def _validate_eb1_emission_contract(record: dict) -> list[str]:
    profile = record.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise HTTPException(status_code=400, detail="profile_required_for_evidence_bundle_eb1")

    validation = validate_profile_contract(profile.strip(), record)

    if not validation.get("known_profile", False):
        warning = (validation.get("warnings") or [f"unknown_profile:{profile}"])[0]
        raise HTTPException(status_code=400, detail=warning)

    missing = validation.get("missing_required_blocks") or []
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "profile_contract_incomplete",
                "profile": profile.strip(),
                "missing_required_blocks": missing,
                "warnings": validation.get("warnings", []),
            },
        )

    return validation.get("warnings", [])


def create_bundle(record: dict, traces: list[dict], bundle_mode: str = "verified_record_v1") -> dict:
    bundle_id = new_bundle_id()
    try:
        if bundle_mode == "verified_record_v1":
            created = generate_verified_record_bundle(
                record=record,
                traces=traces,
                bundle_id=bundle_id,
                output_dir=bundles_dir(),
            )
        elif bundle_mode == "evidence_bundle_eb1":
            warnings = _validate_eb1_emission_contract(record)
            created = generate_evidence_bundle_eb1(
                record=record,
                traces=traces,
                bundle_id=bundle_id,
                output_dir=bundles_dir(),
            )
            created["warnings"] = warnings
        else:
            raise HTTPException(status_code=400, detail="unsupported_bundle_mode")
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    created["bundle_mode"] = bundle_mode
    return created


def resolve_bundle_download(bundle_id: str):
    path = bundle_path(bundle_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="bundle_not_found_or_expired")
    return path
