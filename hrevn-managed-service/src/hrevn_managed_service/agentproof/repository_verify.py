from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..adapters.agentproof_adapter import verify_session_receipt
class AgentProofRepositoryVerifyError(RuntimeError):
    pass


def expected_repository_state(receipt: dict[str, Any]) -> dict[str, str | None]:
    receipt_verification = verify_session_receipt(receipt)
    if not receipt_verification["valid"]:
        raise AgentProofRepositoryVerifyError("receipt_hash_chain_invalid")

    expected: dict[str, str | None] = {}
    for event in receipt.get("events", []):
        if event.get("event_type") != "file_change":
            continue
        payload = event.get("payload") or {}
        path = payload.get("path")
        if not isinstance(path, str) or not path:
            raise AgentProofRepositoryVerifyError("file_change_path_missing")
        expected[path] = payload.get("after_sha256")
    return expected


def verify_repository_state(receipt: dict[str, Any], repository: Path) -> dict[str, Any]:
    repo_root = repository.expanduser().resolve()
    if not repo_root.is_dir():
        raise AgentProofRepositoryVerifyError("repository_directory_missing")
    expected = expected_repository_state(receipt)
    files: list[dict[str, Any]] = []

    for relative_path, expected_sha256 in sorted(expected.items()):
        candidate = (repo_root / relative_path).resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise AgentProofRepositoryVerifyError("repository_path_escape") from exc

        exists = candidate.is_file()
        current_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest() if exists else None
        if expected_sha256 is None:
            status = "match" if not exists else "unexpected_present"
        elif not exists:
            status = "missing"
        elif current_sha256 == expected_sha256:
            status = "match"
        else:
            status = "modified"
        files.append(
            {
                "path": relative_path,
                "status": status,
                "expected_sha256": expected_sha256,
                "current_sha256": current_sha256,
            }
        )

    mismatches = [item for item in files if item["status"] != "match"]
    return {
        "result": "MATCH" if not mismatches else "MISMATCH",
        "valid": not mismatches,
        "repository_root": str(repo_root),
        "checked_file_count": len(files),
        "files": files,
        "mismatches": mismatches,
    }
