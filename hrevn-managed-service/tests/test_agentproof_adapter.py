from __future__ import annotations

import base64
import json
import zipfile
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from hrevn_managed_service.adapters.agentproof_adapter import (
    AgentProofContractError,
    build_agentproof_eb1_record,
    build_agentproof_eb1_record_from_receipt,
    build_session_receipt,
    canonical_json_bytes,
    verify_session_receipt,
)
from hrevn_managed_service.config import settings
from hrevn_managed_service.services.bundle_service import create_bundle, verify_bundle_source
from hrevn_managed_service.services.eb1_profile_registry import resolve_eb1_package_type
from hrevn_managed_service.services.profile_contracts import (
    AGENTPROOF_CODEX_SESSION_V1,
    PROFILE_CONTRACTS,
    validate_profile_contract,
)


def _session() -> dict:
    return {
        "session_id": "codex-session-demo-001",
        "agent_name": "Codex",
        "model": "gpt-5.6",
        "repository_id": "sha256:repo-demo",
        "base_commit": "1" * 40,
        "head_commit": "2" * 40,
        "started_at": "2026-07-17T18:00:00Z",
        "ended_at": "2026-07-17T18:04:00Z",
    }


def _events() -> list[dict]:
    return [
        {
            "event_type": "command",
            "occurred_at": "2026-07-17T18:00:10Z",
            "payload": {
                "command_class": "tests",
                "command_sha256": "a" * 64,
                "exit_code": 0,
                "stdout_sha256": "b" * 64,
                "stderr_sha256": "c" * 64,
            },
        },
        {
            "event_type": "file_change",
            "occurred_at": "2026-07-17T18:01:00Z",
            "payload": {
                "path": "src/example.py",
                "change_type": "modified",
                "before_sha256": "d" * 64,
                "after_sha256": "e" * 64,
                "diff_sha256": "f" * 64,
            },
        },
    ]


def test_canonical_json_is_independent_of_key_insertion_order():
    left = {"z": 1, "a": {"y": "cafe\u0301", "x": True}}
    right = {"a": {"x": True, "y": "café"}, "z": 1}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_json_bytes(left).endswith(b"}")
    assert not canonical_json_bytes(left).endswith(b"\n")


def test_receipt_has_internal_hash_chain_and_validates():
    receipt = build_session_receipt(_session(), _events())

    assert receipt["events"][0]["previous_event_hash"] == "0" * 64
    assert receipt["events"][1]["previous_event_hash"] == receipt["events"][0]["event_hash"]
    assert receipt["chain_head_sha256"] == receipt["events"][1]["event_hash"]
    assert verify_session_receipt(receipt)["valid"] is True


@pytest.mark.parametrize("mutation", ["alter", "delete", "reorder"])
def test_receipt_detects_session_tampering(mutation: str):
    receipt = build_session_receipt(_session(), _events())
    tampered = deepcopy(receipt)
    if mutation == "alter":
        tampered["events"][0]["payload"]["exit_code"] = 1
    elif mutation == "delete":
        del tampered["events"][0]
    else:
        tampered["events"].reverse()

    result = verify_session_receipt(tampered)

    assert result["valid"] is False
    assert result["errors"]


def test_raw_command_or_output_content_is_rejected():
    events = _events()
    events[0]["payload"]["command_text"] = "pytest -q"

    with pytest.raises(AgentProofContractError, match="raw_content_forbidden"):
        build_session_receipt(_session(), events)


def test_combined_command_output_commitment_is_supported():
    events = _events()
    events[0]["payload"].pop("stdout_sha256")
    events[0]["payload"].pop("stderr_sha256")
    events[0]["payload"]["output_capture_mode"] = "combined_stream"
    events[0]["payload"]["output_sha256"] = "9" * 64

    receipt = build_session_receipt(_session(), events)

    assert verify_session_receipt(receipt)["valid"] is True
    assert receipt["events"][0]["payload"]["output_capture_mode"] == "combined_stream"


def test_agentproof_record_satisfies_profile_contract():
    record = build_agentproof_eb1_record(_session(), _events())
    result = validate_profile_contract(AGENTPROOF_CODEX_SESSION_V1, record)

    assert result["known_profile"] is True
    assert result["missing_required_blocks"] == []
    assert result["warnings"] == []
    assert record["documents"][0]["role"] == "agent_session_trace"
    assert resolve_eb1_package_type(AGENTPROOF_CODEX_SESSION_V1) == "agentproof_codex_session_bundle"


def test_existing_receipt_can_become_the_exact_authoritative_document():
    receipt = build_session_receipt(_session(), _events())

    record = build_agentproof_eb1_record_from_receipt(receipt)

    assert record["documents"][0]["content"] == canonical_json_bytes(receipt)


def test_invalid_existing_receipt_is_rejected_before_eb1_emission():
    receipt = build_session_receipt(_session(), _events())
    receipt["events"][0]["payload"]["exit_code"] = 9

    with pytest.raises(AgentProofContractError, match="invalid_session_receipt"):
        build_agentproof_eb1_record_from_receipt(receipt)


def test_profile_contract_defines_canonicalization_and_chain():
    document_contract = PROFILE_CONTRACTS[AGENTPROOF_CODEX_SESSION_V1]["authoritative_document_contracts"][
        "agent_session_trace"
    ]

    assert document_contract["canonicalization"]["name"] == "HREVN_CANONICAL_JSON_V1"
    assert document_contract["canonicalization"]["trailing_newline"] is False
    assert document_contract["hash_chain"]["event_hash_scope"] == "canonical_event_without_event_hash"


def test_agentproof_receipt_is_authoritative_in_signed_eb1_and_tamper_fails(tmp_path):
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_key_b64 = base64.b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_key_b64 = base64.b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    setting_overrides = {
        "bundles_dir": tmp_path,
        "hrevn_eb_signing_private_key": private_key_b64,
        "hrevn_eb_signing_public_key": public_key_b64,
        "hrevn_eb_signing_public_key_id": "agentproof-test-key",
        "hrevn_eb_anchor_emit_real": False,
    }
    original_settings = {name: getattr(settings, name) for name in setting_overrides}
    for name, value in setting_overrides.items():
        object.__setattr__(settings, name, value)

    try:
        record = build_agentproof_eb1_record(_session(), _events())
        receipt_bytes = record["documents"][0]["content"]
        created = create_bundle(record=record, traces=[], bundle_mode="evidence_bundle_eb1")
        verification = verify_bundle_source(created["bundle_path"])

        assert verification["valid"] is True
        assert verification["root_hash_match"] is True
        assert verification["signature_status"] == "signed"
        assert verification["signature_valid"] is True

        with zipfile.ZipFile(created["bundle_path"]) as source_zip:
            manifest = json.loads(source_zip.read("manifest.json"))
            assert manifest["authoritative_files"] == ["documents/agent-session.json"]
            assert source_zip.read("documents/agent-session.json") == receipt_bytes

            tampered_receipt = json.loads(receipt_bytes)
            tampered_receipt["events"][0]["payload"]["exit_code"] = 1
            tampered_path = tmp_path / "agentproof-tampered.zip"
            with zipfile.ZipFile(tampered_path, "w", zipfile.ZIP_DEFLATED) as tampered_zip:
                for member in source_zip.infolist():
                    content = source_zip.read(member.filename)
                    if member.filename == "documents/agent-session.json":
                        content = canonical_json_bytes(tampered_receipt)
                    tampered_zip.writestr(member, content)

        tampered_verification = verify_bundle_source(str(tampered_path))
        failed_files = {item["file"] for item in tampered_verification["checksums"]["failed"]}

        assert tampered_verification["valid"] is False
        assert tampered_verification["root_hash_match"] is False
        assert "documents/agent-session.json" in failed_files
        assert any(error.startswith("root_hash_mismatch") for error in tampered_verification["errors"])
    finally:
        for name, value in original_settings.items():
            object.__setattr__(settings, name, value)
