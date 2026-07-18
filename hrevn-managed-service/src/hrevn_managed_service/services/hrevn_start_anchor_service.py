from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from time import sleep
from typing import Any

from ..config import settings
from .blockchain_anchor_service import build_blockchain_anchor_record


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_anchor_record_failed(
    root_hash: str,
    *,
    network: str,
    anchor_method: str,
    error: str,
) -> dict[str, Any]:
    return build_blockchain_anchor_record(
        root_hash,
        network=network,
        anchor_method=anchor_method,
        status="anchor_failed",
        error=error,
    )


def _build_anchor_record_pending(
    root_hash: str,
    *,
    network: str,
    anchor_method: str,
) -> dict[str, Any]:
    return build_blockchain_anchor_record(
        root_hash,
        network=network,
        anchor_method=anchor_method,
        status="anchor_pending",
    )


def _fee_fields_for_attempt(w3: Any, attempt: int) -> dict[str, int]:
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    bump_multiplier = 1 + (attempt * 0.15)

    if base_fee is None:
        gas_price = int(w3.eth.gas_price * bump_multiplier)
        return {"gasPrice": gas_price}

    try:
        priority = int(w3.eth.max_priority_fee)
    except Exception:
        priority = w3.to_wei(1, "gwei")
    priority = max(priority, w3.to_wei(1, "gwei"))
    priority = int(priority * bump_multiplier)
    max_fee = int((int(base_fee) * (2 + attempt)) + priority)
    return {
        "maxPriorityFeePerGas": priority,
        "maxFeePerGas": max_fee,
    }


def _is_retryable_anchor_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = (
        "replacement transaction underpriced",
        "nonce too low",
        "already known",
        "already imported",
    )
    return any(marker in message for marker in retryable_markers)


def _emit_root_hash_to_sepolia(
    root_hash: str,
    *,
    network: str,
    anchor_method: str,
) -> dict[str, Any]:
    rpc_url = settings.hrevn_start_sepolia_rpc_url
    private_key = settings.hrevn_start_sepolia_private_key
    from_address = settings.hrevn_start_sepolia_from_address
    explorer_base_url = settings.hrevn_start_anchor_explorer_base_url
    wait_confirmations = settings.hrevn_start_sepolia_wait_confirmations

    if not rpc_url or not private_key or not from_address:
        return _build_anchor_record_failed(
            root_hash,
            network=network,
            anchor_method=anchor_method,
            error="missing_sepolia_credentials",
        )

    try:
        from eth_account import Account
        from web3 import Web3
    except Exception as exc:
        return _build_anchor_record_failed(
            root_hash,
            network=network,
            anchor_method=anchor_method,
            error=f"web3_not_available:{exc}",
        )

    normalized_root = root_hash.lower().removeprefix("0x")
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url.strip()))
        if not w3.is_connected():
            return _build_anchor_record_failed(
                root_hash,
                network=network,
                anchor_method=anchor_method,
                error="rpc_not_connected",
            )

        chain_id = w3.eth.chain_id
        if chain_id != 11155111:
            return _build_anchor_record_failed(
                root_hash,
                network=network,
                anchor_method=anchor_method,
                error=f"unexpected_chain_id:{chain_id}",
            )

        acct = Account.from_key(private_key.strip())
        from_checksum = Web3.to_checksum_address(from_address.strip())
        if acct.address.lower() != from_checksum.lower():
            return _build_anchor_record_failed(
                root_hash,
                network=network,
                anchor_method=anchor_method,
                error="from_address_mismatch",
            )

        for attempt in range(3):
            try:
                nonce = w3.eth.get_transaction_count(from_checksum, "pending")
                tx: dict[str, Any] = {
                    "chainId": chain_id,
                    "from": from_checksum,
                    "to": from_checksum,
                    "value": 0,
                    "data": "0x" + normalized_root,
                    "nonce": nonce,
                }
                tx.update(_fee_fields_for_attempt(w3, attempt))
                try:
                    estimate = w3.eth.estimate_gas(tx)
                    tx["gas"] = int(estimate * 1.25)
                except Exception:
                    tx["gas"] = 80000

                signed = acct.sign_transaction(tx)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                if receipt.status != 1:
                    return _build_anchor_record_failed(
                        root_hash,
                        network=network,
                        anchor_method=anchor_method,
                        error=f"anchor_tx_failed:{tx_hash.hex()}",
                    )

                confirmations = max(int(wait_confirmations or 1), 1)
                if confirmations > 1:
                    target_block = int(receipt.blockNumber) + confirmations - 1
                    for _ in range(60):
                        if w3.eth.block_number >= target_block:
                            break
                        sleep(1)

                tx_hash_hex = tx_hash.hex()
                record = build_blockchain_anchor_record(
                    root_hash,
                    network=network,
                    anchor_method=anchor_method,
                    transaction_reference=tx_hash_hex,
                    anchored_at=_utc_now(),
                    status="anchored",
                )
                record["block_number"] = receipt.blockNumber
                record["wallet_address"] = from_checksum
                record["explorer_url"] = f"{explorer_base_url.rstrip('/')}/{tx_hash_hex}"
                return record
            except Exception as exc:
                if attempt < 2 and _is_retryable_anchor_error(exc):
                    sleep(1)
                    continue
                return _build_anchor_record_failed(
                    root_hash,
                    network=network,
                    anchor_method=anchor_method,
                    error=f"anchor_exception:{exc}",
                )
    except Exception as exc:
        return _build_anchor_record_failed(
            root_hash,
            network=network,
            anchor_method=anchor_method,
            error=f"anchor_exception:{exc}",
        )


def _anchor_payload(
    payload: dict[str, Any],
    *,
    enabled: bool | None = None,
    emit_real: bool | None = None,
    network: str | None = None,
    anchor_method: str | None = None,
    transaction_reference: str | None = None,
) -> dict[str, Any] | None:
    is_enabled = settings.hrevn_start_anchor_enabled if enabled is None else enabled
    if not is_enabled:
        return None

    target_network = network or settings.hrevn_start_anchor_network
    method = anchor_method or settings.hrevn_start_anchor_method
    root_hash = sha256(_canonical_bytes(payload)).hexdigest()
    tx_reference = (
        _normalize_text(transaction_reference)
        if transaction_reference is not None
        else _normalize_text(settings.hrevn_start_anchor_transaction_reference)
    )

    if tx_reference:
        record = build_blockchain_anchor_record(
            root_hash,
            network=target_network,
            anchor_method=method,
            transaction_reference=tx_reference,
        )
    else:
        should_emit_real = settings.hrevn_start_anchor_emit_real if emit_real is None else emit_real
        if not should_emit_real:
            record = _build_anchor_record_pending(
                root_hash,
                network=target_network,
                anchor_method=method,
            )
        elif target_network != "sepolia":
            record = _build_anchor_record_failed(
                root_hash,
                network=target_network,
                anchor_method=method,
                error=f"unsupported_hrevn_start_anchor_network:{target_network}",
            )
        else:
            record = _emit_root_hash_to_sepolia(
                root_hash,
                network=target_network,
                anchor_method=method,
            )

    return {
        "payload": payload,
        "payload_sha256": root_hash,
        "anchor_record": record,
    }


def build_policy_anchor_payload(
    *,
    artifact_id: str,
    verification_code: str,
    verification_url: str,
    organization_name: str,
    organization_tax_id: str,
    representative_name: str,
    representative_role: str,
    policy_version: str,
    issue_date: str | None,
    effective_date: str | None,
    language: str,
) -> dict[str, Any]:
    return {
        "product": "hrevn_start_policy",
        "artifact_id": artifact_id,
        "verification_code": verification_code,
        "verification_url": verification_url,
        "organization_name": organization_name,
        "organization_tax_id": organization_tax_id,
        "representative_name": representative_name,
        "representative_role": representative_role,
        "policy_version": policy_version,
        "issue_date": issue_date,
        "effective_date": effective_date,
        "language": language,
    }


def build_course_anchor_payload(
    *,
    artifact_id: str,
    verification_code: str,
    verification_url: str,
    full_name: str,
    email: str,
    organization_name: str,
    course_version: str,
    completed_at: str | None,
    issued_at: str | None,
    language: str,
    identity_confirmed: bool,
) -> dict[str, Any]:
    return {
        "product": "hrevn_start_course_certificate",
        "artifact_id": artifact_id,
        "verification_code": verification_code,
        "verification_url": verification_url,
        "full_name": full_name,
        "email": email.strip().lower(),
        "organization_name": organization_name,
        "course_version": course_version,
        "completed_at": completed_at,
        "issued_at": issued_at,
        "language": language,
        "identity_confirmed": identity_confirmed,
    }


def anchor_policy_artifact(
    payload: dict[str, Any],
    *,
    enabled: bool | None = None,
    emit_real: bool | None = None,
    network: str | None = None,
    anchor_method: str | None = None,
    transaction_reference: str | None = None,
) -> dict[str, Any] | None:
    return _anchor_payload(
        payload,
        enabled=enabled,
        emit_real=emit_real,
        network=network,
        anchor_method=anchor_method,
        transaction_reference=transaction_reference,
    )


def anchor_course_artifact(
    payload: dict[str, Any],
    *,
    enabled: bool | None = None,
    emit_real: bool | None = None,
    network: str | None = None,
    anchor_method: str | None = None,
    transaction_reference: str | None = None,
) -> dict[str, Any] | None:
    return _anchor_payload(
        payload,
        enabled=enabled,
        emit_real=emit_real,
        network=network,
        anchor_method=anchor_method,
        transaction_reference=transaction_reference,
    )
