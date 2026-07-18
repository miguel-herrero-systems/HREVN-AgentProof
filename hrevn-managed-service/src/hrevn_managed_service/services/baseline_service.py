from __future__ import annotations

from typing import Any
from types import SimpleNamespace

from ..adapters.core_adapter import build_baseline_engine
from .profile_contracts import validate_profile_contract


def _compose_payload(task_type: str | None, profile: str | None, record: dict[str, Any] | None, metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if record:
        payload.update(record)
    if task_type:
        payload["task_type"] = task_type
    if profile:
        payload["profile"] = profile
    if metadata:
        payload["metadata"] = metadata
    return payload


def run_baseline_check(task_type: str | None, profile: str | None, record: dict[str, Any] | None, metadata: dict[str, Any] | None):
    engine = build_baseline_engine()
    payload = _compose_payload(task_type, profile, record, metadata)
    return engine.run(payload)


def run_profile_validate(profile: str, record: dict[str, Any], metadata: dict[str, Any] | None):
    result = run_baseline_check(task_type=None, profile=profile, record=record, metadata=metadata)
    overlay = validate_profile_contract(profile, record)

    missing_required_blocks = list(dict.fromkeys([*result.missing_required_blocks, *overlay["missing_required_blocks"]]))
    risk_flags = list(dict.fromkeys([*result.risk_flags, *overlay["warnings"]]))

    readiness_level = result.readiness_level
    if missing_required_blocks and readiness_level == "high":
        readiness_level = "medium"

    merged_result = SimpleNamespace(
        result=result.result,
        profile_detected=result.profile_detected,
        readiness_level=readiness_level,
        missing_required_blocks=missing_required_blocks,
        risk_flags=risk_flags,
        recommended_next_step=result.recommended_next_step,
        remedy_payload=result.remedy_payload,
        check_id=result.check_id,
        checked_at=result.checked_at,
        profile_contract=overlay["details"],
    )

    if overlay.get("known_profile") and overlay["missing_required_blocks"]:
        validation_status = overlay["validation_status"]
    else:
        validation_status = "ready_for_full_validation" if readiness_level == "high" else result.recommended_next_step

    return merged_result, validation_status
