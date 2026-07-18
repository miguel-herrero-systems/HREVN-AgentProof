from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from ..services.profile_contracts import AGENTPROOF_CODEX_SESSION_V1, PROFILE_CONTRACTS


TRACE_ROLE = "agent_session_trace"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RAW_CONTENT_KEYS = {
    "command_text",
    "stdout_text",
    "stderr_text",
    "diff_text",
    "file_content",
    "prompt_text",
}


class AgentProofContractError(ValueError):
    pass


def _trace_contract() -> dict[str, Any]:
    profile_contract = PROFILE_CONTRACTS[AGENTPROOF_CODEX_SESSION_V1]
    return profile_contract["authoritative_document_contracts"][TRACE_ROLE]


def _normalize_json_value(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise AgentProofContractError(f"floating_point_not_allowed:{path}")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentProofContractError(f"non_string_key:{path}")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise AgentProofContractError(f"duplicate_normalized_key:{path}.{normalized_key}")
            normalized[normalized_key] = _normalize_json_value(item, f"{path}.{normalized_key}")
        return normalized
    raise AgentProofContractError(f"unsupported_json_type:{path}:{type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    spec = _trace_contract()["canonicalization"]
    if spec["name"] != "HREVN_CANONICAL_JSON_V1" or spec["encoding"] != "utf-8":
        raise AgentProofContractError("unsupported_canonicalization_contract")
    normalized = _normalize_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=tuple(spec["item_separators"]),
        allow_nan=False,
    ).encode(spec["encoding"])


def _sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_hash(value: Any, field: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise AgentProofContractError(f"invalid_sha256:{field}")


def _require_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentProofContractError(f"missing_timestamp:{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AgentProofContractError(f"invalid_timestamp:{field}") from exc
    if parsed.tzinfo is None:
        raise AgentProofContractError(f"timezone_required:{field}")


def _reject_raw_content(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _RAW_CONTENT_KEYS:
                raise AgentProofContractError(f"raw_content_forbidden:{path}.{key}")
            _reject_raw_content(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_raw_content(item, f"{path}[{index}]")


def _validate_repo_path(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentProofContractError("missing_repository_relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("~"):
        raise AgentProofContractError("unsafe_repository_relative_path")


def _validate_event_input(event: dict[str, Any], index: int) -> None:
    event_type = event.get("event_type")
    payload = event.get("payload")
    if event_type not in {"command", "file_change"}:
        raise AgentProofContractError(f"unsupported_event_type:{index}")
    _require_timestamp(event.get("occurred_at"), f"events[{index}].occurred_at")
    if not isinstance(payload, dict):
        raise AgentProofContractError(f"invalid_event_payload:{index}")
    _reject_raw_content(payload)

    if event_type == "command":
        _require_hash(payload.get("command_sha256"), "command_sha256")
        capture_mode = payload.get("output_capture_mode", "separate_streams")
        if capture_mode == "separate_streams":
            _require_hash(payload.get("stdout_sha256"), "stdout_sha256")
            _require_hash(payload.get("stderr_sha256"), "stderr_sha256")
        elif capture_mode == "combined_stream":
            _require_hash(payload.get("output_sha256"), "output_sha256")
        else:
            raise AgentProofContractError("unsupported_output_capture_mode")
        if not isinstance(payload.get("exit_code"), int):
            raise AgentProofContractError("invalid_exit_code")
    else:
        _validate_repo_path(payload.get("path"))
        if payload.get("change_type") not in {"created", "modified", "deleted"}:
            raise AgentProofContractError("invalid_change_type")
        _require_hash(payload.get("before_sha256"), "before_sha256", nullable=True)
        _require_hash(payload.get("after_sha256"), "after_sha256", nullable=True)
        _require_hash(payload.get("diff_sha256"), "diff_sha256")


def build_session_receipt(session: dict[str, Any], event_inputs: list[dict[str, Any]]) -> dict[str, Any]:
    contract = _trace_contract()
    chain_spec = contract["hash_chain"]
    previous_hash = chain_spec["genesis_previous_hash"]
    events: list[dict[str, Any]] = []

    for index, event_input in enumerate(event_inputs, start=chain_spec["sequence_start"]):
        _validate_event_input(event_input, index)
        event = {
            "sequence": index,
            "event_type": event_input["event_type"],
            "occurred_at": event_input["occurred_at"],
            "previous_event_hash": previous_hash,
            "payload": deepcopy(event_input["payload"]),
        }
        event_hash = _sha256_hex(canonical_json_bytes(event))
        event["event_hash"] = event_hash
        events.append(event)
        previous_hash = event_hash

    if not events:
        raise AgentProofContractError("session_requires_at_least_one_event")

    for field in ("session_id", "agent_name", "model", "repository_id", "base_commit", "head_commit"):
        if not isinstance(session.get(field), str) or not session[field].strip():
            raise AgentProofContractError(f"missing_session_field:{field}")
    _require_timestamp(session.get("started_at"), "started_at")
    _require_timestamp(session.get("ended_at"), "ended_at")

    return {
        "schema_version": contract["schema_version"],
        "canonicalization": contract["canonicalization"]["name"],
        "session_id": session["session_id"],
        "agent_name": session["agent_name"],
        "model": session["model"],
        "repository_id": session["repository_id"],
        "base_commit": session["base_commit"],
        "head_commit": session["head_commit"],
        "started_at": session["started_at"],
        "ended_at": session["ended_at"],
        "event_count": len(events),
        "chain_head_sha256": previous_hash,
        "events": events,
    }


def verify_session_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    contract = _trace_contract()
    chain_spec = contract["hash_chain"]
    previous_hash = chain_spec["genesis_previous_hash"]
    errors: list[dict[str, Any]] = []
    events = receipt.get("events")
    if not isinstance(events, list):
        return {"valid": False, "errors": [{"code": "events_not_array"}]}

    for offset, event in enumerate(events):
        expected_sequence = chain_spec["sequence_start"] + offset * chain_spec["sequence_step"]
        if not isinstance(event, dict):
            errors.append({"code": "event_not_object", "sequence": expected_sequence})
            continue
        sequence = event.get("sequence")
        if sequence != expected_sequence:
            errors.append({"code": "sequence_mismatch", "sequence": sequence, "expected": expected_sequence})
        if event.get("previous_event_hash") != previous_hash:
            errors.append({"code": "previous_hash_mismatch", "sequence": sequence})
        try:
            _validate_event_input(
                {
                    "event_type": event.get("event_type"),
                    "occurred_at": event.get("occurred_at"),
                    "payload": event.get("payload"),
                },
                expected_sequence,
            )
        except AgentProofContractError as exc:
            errors.append(
                {
                    "code": "event_contract_invalid",
                    "sequence": sequence,
                    "detail": str(exc),
                }
            )
        declared_hash = event.get("event_hash")
        event_scope = {key: value for key, value in event.items() if key != "event_hash"}
        recalculated_hash = _sha256_hex(canonical_json_bytes(event_scope))
        if declared_hash != recalculated_hash:
            errors.append(
                {
                    "code": "event_hash_mismatch",
                    "sequence": sequence,
                    "declared": declared_hash,
                    "recalculated": recalculated_hash,
                }
            )
        previous_hash = declared_hash if isinstance(declared_hash, str) else recalculated_hash

    if receipt.get("event_count") != len(events):
        errors.append({"code": "event_count_mismatch", "expected": len(events)})
    if receipt.get("chain_head_sha256") != previous_hash:
        errors.append({"code": "chain_head_mismatch", "recalculated": previous_hash})

    return {
        "valid": not errors,
        "event_count": len(events),
        "chain_head_sha256": previous_hash,
        "errors": errors,
    }


def build_agentproof_eb1_record(session: dict[str, Any], event_inputs: list[dict[str, Any]]) -> dict[str, Any]:
    receipt = build_session_receipt(session, event_inputs)
    return build_agentproof_eb1_record_from_receipt(receipt)


def build_agentproof_eb1_record_from_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    verification = verify_session_receipt(receipt)
    if not verification["valid"]:
        raise AgentProofContractError("invalid_session_receipt")
    if receipt.get("schema_version") != _trace_contract()["schema_version"]:
        raise AgentProofContractError("unsupported_session_receipt_schema")

    contract = _trace_contract()
    return {
        "profile": AGENTPROOF_CODEX_SESSION_V1,
        "profile_inputs": {
            key: receipt[key]
            for key in (
                "session_id",
                "agent_name",
                "model",
                "started_at",
                "ended_at",
                "repository_id",
                "base_commit",
                "head_commit",
                "event_count",
                "chain_head_sha256",
            )
        },
        "package_title": f"AgentProof receipt · {receipt['session_id']}",
        "package_summary": "Tamper-evident receipt for an instrumented Codex session.",
        "issued_by": "HREVN AgentProof",
        "language": "en",
        "anchor_network": "sepolia",
        "documents": [
            {
                "filename": contract["filename"],
                "role": TRACE_ROLE,
                "media_type": "application/json",
                "authoritative": True,
                "content": canonical_json_bytes(receipt),
            }
        ],
        "images": [],
        "attachments": [],
    }
