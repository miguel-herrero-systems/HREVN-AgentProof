from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from hrevn_managed_service.adapters.agentproof_adapter import build_session_receipt, canonical_json_bytes
from hrevn_managed_service.agentproof.seal import AgentProofSealError, seal_receipt


class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self) -> bytes:
        return self._body


def _receipt() -> dict:
    return build_session_receipt(
        {
            "session_id": "codex-seal-test-001",
            "agent_name": "Codex CLI",
            "model": "gpt-5.6-sol",
            "repository_id": "sha256:repository",
            "base_commit": "1" * 40,
            "head_commit": "2" * 40,
            "started_at": "2026-07-17T20:00:00Z",
            "ended_at": "2026-07-17T20:02:00Z",
        },
        [
            {
                "event_type": "command",
                "occurred_at": "2026-07-17T20:00:10Z",
                "payload": {
                    "command_class": "shell",
                    "command_sha256": "a" * 64,
                    "output_capture_mode": "combined_stream",
                    "output_sha256": "b" * 64,
                    "exit_code": 0,
                },
            }
        ],
    )


def _write_receipt(path: Path, receipt: dict | None = None) -> dict:
    value = receipt or _receipt()
    path.write_bytes(canonical_json_bytes(value))
    return value


def _api_response(*, signature_status: str = "signed", anchor_status: str = "anchored") -> dict:
    anchor = {
        "root_hash": "c" * 64,
        "network": "sepolia",
        "anchor_method": "eth_data_transaction",
        "transaction_reference": "0x" + "d" * 64 if anchor_status == "anchored" else None,
    }
    return {
        "output_version": "1.0",
        "result": "GENERATED",
        "bundle_id": "BND-AGENTPROOF01",
        "download_url": "/v1/bundles/BND-AGENTPROOF01/download",
        "expires_at": "2026-07-18T20:00:00Z",
        "metadata": {
            "record_id": "EB1-AGENTPROOF01",
            "verification_url": "https://hrevn.com/verify/evidence-bundle/?bundle_id=BND-AGENTPROOF01",
            "schema_version": "hrevn-eb1-v1",
            "bundle_mode": "evidence_bundle_eb1",
            "bundle_profile": "evidence_bundle_eb1_v1",
            "package_type": "agentproof_codex_session_bundle",
            "root_hash": "c" * 64,
            "anchor_status": anchor_status,
            "anchor": anchor,
            "signature_status": signature_status,
            "signature_algorithm": "Ed25519",
            "signature_public_key_id": "hrevn-eb-ed25519-01",
            "warnings": [],
        },
    }


def test_seal_posts_exact_canonical_receipt_and_bearer_without_returning_secret(tmp_path):
    receipt_path = tmp_path / "agent-session.json"
    receipt = _write_receipt(receipt_path)
    captured = {}

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _FakeResponse(_api_response())

    response = seal_receipt(
        receipt_path,
        api_base_url="https://api.example.test/",
        api_key="secret-test-key",
        opener=opener,
    )

    document = captured["payload"]["record"]["documents"][0]
    assert captured["url"] == "https://api.example.test/v1/generate-bundle"
    assert captured["authorization"] == "Bearer secret-test-key"
    assert document["role"] == "agent_session_trace"
    assert document["content"].encode("utf-8") == canonical_json_bytes(receipt)
    assert "secret-test-key" not in json.dumps(response)
    assert response["public_download_url"].endswith("/v1/public/bundles/BND-AGENTPROOF01/download")


def test_noncanonical_receipt_is_rejected_before_http(tmp_path):
    receipt_path = tmp_path / "agent-session.json"
    receipt_path.write_text(json.dumps(_receipt(), indent=2), encoding="utf-8")
    called = False

    def opener(_request, *, timeout):
        nonlocal called
        called = True
        raise AssertionError(timeout)

    with pytest.raises(AgentProofSealError, match="receipt_not_canonical"):
        seal_receipt(receipt_path, api_base_url="https://api.example.test", opener=opener)
    assert called is False


def test_altered_hash_chain_is_rejected_before_http(tmp_path):
    receipt_path = tmp_path / "agent-session.json"
    tampered = deepcopy(_receipt())
    tampered["events"][0]["payload"]["exit_code"] = 9
    _write_receipt(receipt_path, tampered)

    with pytest.raises(AgentProofSealError, match="receipt_hash_chain_invalid"):
        seal_receipt(
            receipt_path,
            api_base_url="https://api.example.test",
            opener=lambda *_args, **_kwargs: pytest.fail("HTTP must not be called"),
        )


def test_unsigned_or_pending_bundle_is_rejected_unless_explicitly_allowed(tmp_path):
    receipt_path = tmp_path / "agent-session.json"
    _write_receipt(receipt_path)
    pending = _api_response(signature_status="signing_not_configured", anchor_status="anchor_pending")

    with pytest.raises(AgentProofSealError, match="bundle_not_signed"):
        seal_receipt(
            receipt_path,
            api_base_url="https://api.example.test",
            opener=lambda *_args, **_kwargs: _FakeResponse(pending),
        )

    response = seal_receipt(
        receipt_path,
        api_base_url="https://api.example.test",
        allow_pending=True,
        opener=lambda *_args, **_kwargs: _FakeResponse(pending),
    )
    assert response["metadata"]["anchor_status"] == "anchor_pending"
