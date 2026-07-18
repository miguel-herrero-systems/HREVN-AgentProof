from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hrevn_managed_service.adapters.agentproof_adapter import (
    build_session_receipt,
    canonical_json_bytes,
)
from hrevn_managed_service.agentproof.github_action import (
    AgentProofActionError,
    build_pull_request_comment,
    publish_pull_request_comment,
    verify_seal_and_export,
)


class _FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self):
        return self.body


def _receipt(repo: Path) -> dict:
    content = (repo / "calculator.py").read_bytes()
    return build_session_receipt(
        {
            "session_id": "codex-action-test-001",
            "agent_name": "Codex CLI",
            "model": "gpt-5.6-sol",
            "repository_id": "sha256:repository",
            "base_commit": "1" * 40,
            "head_commit": "2" * 40,
            "started_at": "2026-07-18T08:00:00Z",
            "ended_at": "2026-07-18T08:01:00Z",
        },
        [
            {
                "event_type": "file_change",
                "occurred_at": "2026-07-18T08:00:30Z",
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


def _seal_response() -> dict:
    return {
        "bundle_id": "BND-ACTION1234",
        "public_download_url": "https://proof.example/BND-ACTION1234.zip",
        "public_sha256_url": "https://proof.example/BND-ACTION1234.zip.sha256",
        "metadata": {
            "root_hash": "c" * 64,
            "signature_status": "signed",
            "signature_algorithm": "Ed25519",
            "signature_public_key_id": "agentproof-key-01",
            "anchor_status": "anchored",
            "verification_url": "https://proof.example/verify/BND-ACTION1234",
            "anchor": {
                "network": "sepolia",
                "transaction_reference": "d" * 64,
            },
        },
    }


def _prepare(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    receipt_path = tmp_path / "agent-session.json"
    receipt_path.write_bytes(canonical_json_bytes(_receipt(repo)))
    return repo, receipt_path


def test_action_verifies_seals_and_exports_clean_artifact(tmp_path):
    repo, receipt_path = _prepare(tmp_path)
    output = tmp_path / "result"
    bundle_bytes = b"signed-eb1-bundle"
    sidecar = f"{hashlib.sha256(bundle_bytes).hexdigest()}  BND-ACTION1234.zip\n".encode()
    captured = {}

    def sealer(path, **kwargs):
        captured.update({"path": path, **kwargs})
        return _seal_response()

    def downloader(url):
        return sidecar if url.endswith(".sha256") else bundle_bytes

    result = verify_seal_and_export(
        receipt_path=receipt_path,
        repository_path=repo,
        result_directory=output,
        api_base_url="https://api.example",
        api_key="masked-secret",
        sealer=sealer,
        downloader=downloader,
    )

    assert result["result"] == "AGENT_VERIFIED"
    assert result["repository_verification"]["result"] == "MATCH"
    assert "repository_root" not in result["repository_verification"]
    assert result["bundle"]["transaction_reference"] == "0x" + "d" * 64
    assert result["bundle"]["transaction_explorer_url"] == (
        "https://sepolia.etherscan.io/tx/0x" + "d" * 64
    )
    assert captured["api_key"] == "masked-secret"
    assert (output / "BND-ACTION1234.zip").read_bytes() == bundle_bytes
    assert (output / "agent-session.json").read_bytes() == receipt_path.read_bytes()
    exported = (output / "result.json").read_text(encoding="utf-8")
    assert "masked-secret" not in exported
    assert str(tmp_path) not in exported


def test_action_stops_before_sealing_when_repository_changed(tmp_path):
    repo, receipt_path = _prepare(tmp_path)
    (repo / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    with pytest.raises(AgentProofActionError, match="repository_state_mismatch:calculator.py"):
        verify_seal_and_export(
            receipt_path=receipt_path,
            repository_path=repo,
            result_directory=tmp_path / "result",
            api_base_url="https://api.example",
            api_key="secret",
            sealer=lambda *_args, **_kwargs: pytest.fail("must not seal a mismatch"),
        )


def test_action_rejects_download_when_sidecar_does_not_match(tmp_path):
    repo, receipt_path = _prepare(tmp_path)

    with pytest.raises(AgentProofActionError, match="bundle_sidecar_mismatch"):
        verify_seal_and_export(
            receipt_path=receipt_path,
            repository_path=repo,
            result_directory=tmp_path / "result",
            api_base_url="https://api.example",
            api_key="secret",
            sealer=lambda *_args, **_kwargs: _seal_response(),
            downloader=lambda url: b"0" * 64 if url.endswith(".sha256") else b"bundle",
        )


def test_pull_request_comment_is_precise_and_contains_no_secret():
    result = {
        "repository_verification": {"result": "MATCH", "checked_file_count": 2},
        "bundle": {
            "bundle_id": "BND-ACTION1234",
            "signature_status": "signed",
            "anchor_status": "anchored",
            "transaction_reference": "0x" + "d" * 64,
            "transaction_explorer_url": "https://sepolia.etherscan.io/tx/0x" + "d" * 64,
            "verification_url": "https://proof.example/verify",
            "download_url": "https://proof.example/download",
        },
    }
    comment = build_pull_request_comment(result, artifact_url="https://github.example/artifact")

    assert "<!-- hrevn-agentproof -->" in comment
    assert "Agent-verified" in comment
    assert "MATCH" in comment
    assert "(2 files)" in comment
    assert "tamper-evident, not exhaustive" in comment
    assert "super-secret" not in comment


def test_publish_comment_updates_existing_agentproof_comment():
    result = {
        "repository_verification": {"result": "MATCH", "checked_file_count": 1},
        "bundle": {
            "bundle_id": "BND-ACTION1234",
            "signature_status": "signed",
            "anchor_status": "anchored",
            "transaction_reference": "0x" + "d" * 64,
            "transaction_explorer_url": None,
            "verification_url": "https://proof.example/verify",
            "download_url": "https://proof.example/download",
        },
    }
    requests = []

    def opener(request, *, timeout):
        requests.append((request.method, request.full_url, request.get_header("Authorization")))
        if request.method == "GET":
            return _FakeResponse([{"id": 42, "body": "<!-- hrevn-agentproof --> old"}])
        return _FakeResponse({"html_url": "https://github.example/comment/42"})

    response = publish_pull_request_comment(
        result=result,
        token="github-secret",
        repository="hrevn/agentproof",
        pull_request_number=7,
        opener=opener,
    )

    assert response["action"] == "updated"
    assert "(1 file)" in build_pull_request_comment(result)
    assert requests[0][0] == "GET"
    assert requests[1][0] == "PATCH"
    assert requests[1][1].endswith("/issues/comments/42")
    assert all(header == "Bearer github-secret" for _method, _url, header in requests)
