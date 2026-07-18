from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..adapters.agentproof_adapter import canonical_json_bytes, verify_session_receipt
from ..services.bundle_service import resolve_bundle_download, verify_bundle_source


router = APIRouter(tags=["agentproof"])
_BUNDLE_ID_RE = re.compile(r"^BND-[A-Z0-9]{8,32}$")
_AGENTPROOF_PACKAGE_TYPE = "agentproof_codex_session_bundle"
_RECEIPT_PATH = "documents/agent-session.json"


def _safe_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "sequence": event.get("sequence"),
        "event_type": event.get("event_type"),
        "occurred_at": event.get("occurred_at"),
        "previous_event_hash": event.get("previous_event_hash"),
        "event_hash": event.get("event_hash"),
        "payload": payload,
    }


@router.get("/v1/public/agentproof/bundles/{bundle_id}")
def public_agentproof_bundle(bundle_id: str) -> dict[str, Any]:
    if not _BUNDLE_ID_RE.fullmatch(bundle_id):
        raise HTTPException(status_code=400, detail="invalid_bundle_id")
    bundle_path = Path(resolve_bundle_download(bundle_id))
    verification = verify_bundle_source(str(bundle_path))
    verification["source"] = bundle_id
    if verification.get("package_type") != _AGENTPROOF_PACKAGE_TYPE:
        raise HTTPException(status_code=400, detail="not_agentproof_bundle")

    try:
        with zipfile.ZipFile(bundle_path) as bundle_zip:
            receipt_bytes = bundle_zip.read(_RECEIPT_PATH)
            receipt = json.loads(receipt_bytes)
    except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="agentproof_receipt_unreadable") from exc
    if not isinstance(receipt, dict):
        raise HTTPException(status_code=422, detail="agentproof_receipt_invalid")

    semantic = verify_session_receipt(receipt)
    canonical_match = receipt_bytes == canonical_json_bytes(receipt)
    return {
        "output_version": "1.0",
        "bundle_id": bundle_id,
        "valid": bool(verification.get("valid") and semantic["valid"] and canonical_match),
        "cryptographic_verification": verification,
        "session_verification": {
            **semantic,
            "canonical_bytes_match": canonical_match,
        },
        "session": {
            key: receipt.get(key)
            for key in (
                "session_id",
                "agent_name",
                "model",
                "repository_id",
                "base_commit",
                "head_commit",
                "started_at",
                "ended_at",
                "event_count",
                "chain_head_sha256",
            )
        },
        "events": [_safe_event(event) for event in receipt.get("events", []) if isinstance(event, dict)],
        "download_url": f"/v1/public/bundles/{bundle_id}/download",
        "sha256_url": f"/v1/public/bundles/{bundle_id}/sha256",
    }
