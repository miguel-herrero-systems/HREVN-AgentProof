from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..adapters.agentproof_adapter import (
    AgentProofContractError,
    build_agentproof_eb1_record_from_receipt,
    canonical_json_bytes,
    verify_session_receipt,
)
from ..services.eb1_profile_registry import resolve_eb1_package_type
from ..services.profile_contracts import AGENTPROOF_CODEX_SESSION_V1


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_BUNDLE_PROFILE = "evidence_bundle_eb1_v1"
_EXPECTED_PACKAGE_TYPE = resolve_eb1_package_type(AGENTPROOF_CODEX_SESSION_V1)


class AgentProofSealError(RuntimeError):
    pass


def load_canonical_receipt(path: Path) -> tuple[dict[str, Any], bytes]:
    source = path.expanduser().resolve()
    try:
        receipt_bytes = source.read_bytes()
        receipt = json.loads(receipt_bytes)
    except OSError as exc:
        raise AgentProofSealError("receipt_not_readable") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentProofSealError("receipt_not_valid_json") from exc

    if not isinstance(receipt, dict):
        raise AgentProofSealError("receipt_must_be_object")
    try:
        canonical_bytes = canonical_json_bytes(receipt)
    except AgentProofContractError as exc:
        raise AgentProofSealError("receipt_not_canonicalizable") from exc
    if receipt_bytes != canonical_bytes:
        raise AgentProofSealError("receipt_not_canonical")

    verification = verify_session_receipt(receipt)
    if not verification["valid"]:
        raise AgentProofSealError("receipt_hash_chain_invalid")
    return receipt, receipt_bytes


def build_generate_bundle_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    try:
        record = build_agentproof_eb1_record_from_receipt(receipt)
    except (AgentProofContractError, KeyError) as exc:
        raise AgentProofSealError("receipt_contract_invalid") from exc

    document = record["documents"][0]
    content = document.get("content")
    if not isinstance(content, bytes):
        raise AgentProofSealError("authoritative_document_not_bytes")
    document["content"] = content.decode("utf-8")
    return {
        "bundle_mode": "evidence_bundle_eb1",
        "record": record,
        "traces": [],
    }


def _read_http_error(exc: HTTPError) -> str:
    try:
        body = exc.read(4096).decode("utf-8", errors="replace")
    except OSError:
        return ""
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        return ""
    detail = decoded.get("detail") if isinstance(decoded, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("error_code") or "")
    if isinstance(detail, str):
        return detail[:120]
    return ""


def _validate_seal_response(response: dict[str, Any], *, allow_pending: bool) -> None:
    if response.get("result") != "GENERATED" or not response.get("bundle_id"):
        raise AgentProofSealError("bundle_generation_failed")
    metadata = response.get("metadata")
    if not isinstance(metadata, dict):
        raise AgentProofSealError("bundle_metadata_missing")
    if metadata.get("bundle_profile") != _EXPECTED_BUNDLE_PROFILE:
        raise AgentProofSealError("bundle_profile_mismatch")
    if metadata.get("package_type") != _EXPECTED_PACKAGE_TYPE:
        raise AgentProofSealError("bundle_package_type_mismatch")
    root_hash = metadata.get("root_hash")
    if not isinstance(root_hash, str) or not _SHA256_RE.fullmatch(root_hash):
        raise AgentProofSealError("bundle_root_hash_invalid")

    signature_status = metadata.get("signature_status")
    anchor_status = metadata.get("anchor_status")
    if allow_pending:
        if signature_status not in {"signed", "signing_not_configured"}:
            raise AgentProofSealError(f"bundle_signature_failed:{signature_status or 'missing'}")
        if anchor_status not in {"anchored", "anchor_pending"}:
            raise AgentProofSealError(f"bundle_anchor_failed:{anchor_status or 'missing'}")
        return

    if signature_status != "signed":
        raise AgentProofSealError(f"bundle_not_signed:{signature_status or 'missing'}")
    if anchor_status != "anchored":
        raise AgentProofSealError(f"bundle_not_anchored:{anchor_status or 'missing'}")
    anchor = metadata.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("transaction_reference"):
        raise AgentProofSealError("bundle_anchor_transaction_missing")


def seal_receipt(
    receipt_path: Path,
    *,
    api_base_url: str,
    api_key: str | None = None,
    allow_pending: bool = False,
    timeout_seconds: float = 90,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    receipt, _receipt_bytes = load_canonical_receipt(receipt_path)
    payload = build_generate_bundle_payload(receipt)
    endpoint = f"{api_base_url.rstrip('/')}/v1/generate-bundle"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with opener(request, timeout=timeout_seconds) as http_response:
            response = json.loads(http_response.read())
    except HTTPError as exc:
        error_code = _read_http_error(exc)
        suffix = f":{error_code}" if error_code else ""
        raise AgentProofSealError(f"bundle_api_http_error:{exc.code}{suffix}") from exc
    except URLError as exc:
        raise AgentProofSealError("bundle_api_unreachable") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentProofSealError("bundle_api_invalid_response") from exc

    if not isinstance(response, dict):
        raise AgentProofSealError("bundle_api_invalid_response")
    _validate_seal_response(response, allow_pending=allow_pending)

    bundle_id = response["bundle_id"]
    response["public_download_url"] = (
        f"{api_base_url.rstrip('/')}/v1/public/bundles/{bundle_id}/download"
    )
    response["public_sha256_url"] = (
        f"{api_base_url.rstrip('/')}/v1/public/bundles/{bundle_id}/sha256"
    )
    return response
