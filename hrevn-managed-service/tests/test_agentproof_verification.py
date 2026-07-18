from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from hrevn_managed_service.adapters.agentproof_adapter import (
    build_agentproof_eb1_record_from_receipt,
    build_session_receipt,
    canonical_json_bytes,
    verify_session_receipt,
)
from hrevn_managed_service.agentproof.repository_verify import verify_repository_state
from hrevn_managed_service.api.agentproof import public_agentproof_bundle
from hrevn_managed_service.config import settings
from hrevn_managed_service.services.bundle_service import create_bundle


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "agentproof@example.invalid")
    _git(repo, "config", "user.name", "AgentProof Test")
    (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    _git(repo, "add", "calculator.py")
    _git(repo, "commit", "-m", "verified state")


def _receipt(repo: Path) -> dict:
    content = (repo / "calculator.py").read_bytes()
    commit = _git(repo, "rev-parse", "HEAD")
    return build_session_receipt(
        {
            "session_id": "codex-verify-demo-001",
            "agent_name": "Codex CLI",
            "model": "gpt-5.6-sol",
            "repository_id": "sha256:repository",
            "base_commit": commit,
            "head_commit": commit,
            "started_at": "2026-07-17T20:00:00Z",
            "ended_at": "2026-07-17T20:01:00Z",
        },
        [
            {
                "event_type": "file_change",
                "occurred_at": "2026-07-17T20:00:30Z",
                "payload": {
                    "path": "calculator.py",
                    "change_type": "modified",
                    "before_sha256": "a" * 64,
                    "after_sha256": hashlib.sha256(content).hexdigest(),
                    "diff_sha256": "b" * 64,
                    "diff_format": "unified_diff_v1",
                },
            }
        ],
    )


def test_repository_reverification_reports_exact_modified_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    receipt = _receipt(repo)

    green = verify_repository_state(receipt, repo)
    assert green["result"] == "MATCH"
    assert green["valid"] is True

    (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    red = verify_repository_state(receipt, repo)
    assert red["result"] == "MISMATCH"
    assert red["mismatches"][0]["path"] == "calculator.py"
    assert red["mismatches"][0]["status"] == "modified"


def test_repository_reverification_respects_explicit_nested_directory(tmp_path):
    parent = tmp_path / "parent"
    _init_repo(parent)
    example = parent / "examples" / "demo-repository"
    example.mkdir(parents=True)
    (example / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    receipt = _receipt(example)

    result = verify_repository_state(receipt, example)

    assert result["result"] == "MATCH"
    assert result["repository_root"] == str(example.resolve())


def test_semantic_verifier_rejects_raw_content_even_with_rebuilt_hash_chain(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    receipt = _receipt(repo)
    payload = receipt["events"][0]["payload"]
    payload["diff_text"] = "secret source code"
    event_scope = {key: value for key, value in receipt["events"][0].items() if key != "event_hash"}
    receipt["events"][0]["event_hash"] = hashlib.sha256(canonical_json_bytes(event_scope)).hexdigest()
    receipt["chain_head_sha256"] = receipt["events"][0]["event_hash"]

    result = verify_session_receipt(receipt)
    assert result["valid"] is False
    assert any(error["code"] == "event_contract_invalid" for error in result["errors"])


def test_public_agentproof_adapter_returns_safe_timeline(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    receipt = _receipt(repo)
    original_bundles_dir = settings.bundles_dir
    original_anchor = settings.hrevn_eb_anchor_emit_real
    object.__setattr__(settings, "bundles_dir", tmp_path / "bundles")
    object.__setattr__(settings, "hrevn_eb_anchor_emit_real", False)
    try:
        record = build_agentproof_eb1_record_from_receipt(receipt)
        created = create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")
        response = public_agentproof_bundle(created["bundle_id"])
    finally:
        object.__setattr__(settings, "bundles_dir", original_bundles_dir)
        object.__setattr__(settings, "hrevn_eb_anchor_emit_real", original_anchor)

    assert response["valid"] is True
    assert response["session_verification"]["canonical_bytes_match"] is True
    assert response["events"][0]["payload"]["path"] == "calculator.py"
    serialized = canonical_json_bytes(response)
    assert b"secret source code" not in serialized
    assert b"/tmp/" not in serialized
