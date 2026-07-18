from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from hrevn_managed_service.services.blockchain_anchor_service import (
    anchor_eb1_root,
    build_blockchain_anchor_record,
    manifest_anchor_status,
)
from hrevn_managed_service.config import settings


def test_build_blockchain_anchor_record_defaults_to_anchor_pending_without_transaction():
    record = build_blockchain_anchor_record("abc123")

    assert record["root_hash"] == "abc123"
    assert record["network"] == "sepolia"
    assert record["anchor_method"] == "hrevn_managed_anchor"
    assert record["transaction_reference"] is None
    assert record["anchored_at"] is None
    assert record["status"] == "anchor_pending"
    assert manifest_anchor_status(record) == "anchor_pending"


def test_build_blockchain_anchor_record_marks_anchored_when_transaction_exists():
    record = build_blockchain_anchor_record(
        "def456",
        transaction_reference="0xabcde12345",
    )

    assert record["root_hash"] == "def456"
    assert record["transaction_reference"] == "0xabcde12345"
    assert record["status"] == "anchored"
    assert isinstance(record["anchored_at"], str)
    assert record["anchored_at"].endswith("Z")
    assert manifest_anchor_status(record) == "anchored"


def test_build_blockchain_anchor_record_marks_failed_when_error_exists():
    record = build_blockchain_anchor_record(
        "ghi789",
        error="provider_timeout",
    )

    assert record["root_hash"] == "ghi789"
    assert record["status"] == "anchor_failed"
    assert record["anchored_at"] is None
    assert record["error"] == "provider_timeout"
    assert manifest_anchor_status(record) == "anchor_failed"


def test_build_blockchain_anchor_record_respects_explicit_status_and_timestamp():
    record = build_blockchain_anchor_record(
        "xyz000",
        network="ethereum-mainnet",
        anchor_method="manual_import",
        transaction_reference="0x999",
        anchored_at="2026-05-05T18:45:00Z",
        status="anchored",
    )

    assert record == {
        "root_hash": "xyz000",
        "network": "ethereum-mainnet",
        "anchor_method": "manual_import",
        "transaction_reference": "0x999",
        "anchored_at": "2026-05-05T18:45:00Z",
        "status": "anchored",
    }


def test_anchor_eb1_root_returns_failed_for_unsupported_network():
    record = anchor_eb1_root("abc123", network="unsupported-net")

    assert record["network"] == "unsupported-net"
    assert record["status"] == "anchor_failed"
    assert record["error"] == "unsupported_anchor_network:unsupported-net"


def test_anchor_eb1_root_returns_failed_when_base_credentials_missing():
    original_rpc = settings.hrevn_eb_base_rpc_url
    original_pk = settings.hrevn_eb_base_private_key
    original_from = settings.hrevn_eb_base_from_address
    object.__setattr__(settings, "hrevn_eb_base_rpc_url", "")
    object.__setattr__(settings, "hrevn_eb_base_private_key", "")
    object.__setattr__(settings, "hrevn_eb_base_from_address", "")
    try:
        record = anchor_eb1_root("abc123", network="base")
    finally:
        object.__setattr__(settings, "hrevn_eb_base_rpc_url", original_rpc)
        object.__setattr__(settings, "hrevn_eb_base_private_key", original_pk)
        object.__setattr__(settings, "hrevn_eb_base_from_address", original_from)

    assert record["network"] == "base"
    assert record["status"] == "anchor_failed"
    assert record["error"] == "missing_base_credentials"
