from __future__ import annotations

from datetime import datetime, timezone
from time import sleep
from typing import Any, Literal

from ..config import settings


AnchorStatus = Literal["anchored", "anchor_pending", "anchor_failed"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_blockchain_anchor_record(
    root_hash: str,
    *,
    network: str = "sepolia",
    anchor_method: str = "hrevn_managed_anchor",
    transaction_reference: str | None = None,
    anchored_at: str | None = None,
    status: AnchorStatus | None = None,
    error: str | None = None,
    block_number: int | None = None,
    wallet_address: str | None = None,
    explorer_url: str | None = None,
) -> dict[str, Any]:
    if status is None:
        if error:
            status = "anchor_failed"
        elif transaction_reference:
            status = "anchored"
        else:
            status = "anchor_pending"

    record: dict[str, Any] = {
        "root_hash": root_hash,
        "network": network,
        "anchor_method": anchor_method,
        "transaction_reference": transaction_reference,
        "anchored_at": anchored_at or (_utc_now() if status == "anchored" else None),
        "status": status,
    }

    if error:
        record["error"] = error
    if block_number is not None:
        record["block_number"] = block_number
    if wallet_address:
        record["wallet_address"] = wallet_address
    if explorer_url:
        record["explorer_url"] = explorer_url

    return record


def build_anchor_record_pending(
    root_hash: str,
    *,
    network: str,
    wallet_address: str | None = None,
    anchor_method: str = "hrevn_managed_anchor",
    error: str | None = None,
) -> dict[str, Any]:
    return build_blockchain_anchor_record(
        root_hash,
        network=network,
        anchor_method=anchor_method,
        status="anchor_pending" if not error else "anchor_failed",
        error=error,
        wallet_address=wallet_address,
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


def anchor_root_on_evm(
    root_hash: str,
    *,
    network: str,
    rpc_url: str,
    private_key: str,
    from_address: str,
    expected_chain_id: int,
    explorer_base_url: str,
    wait_confirmations: int = 1,
    anchor_method: str = "hrevn_managed_anchor",
) -> dict[str, Any]:
    normalized_root = root_hash.lower().removeprefix("0x")
    wallet_address = from_address.strip() or None

    if not rpc_url or not private_key or not from_address:
        return build_anchor_record_pending(
            root_hash,
            network=network,
            wallet_address=wallet_address,
            anchor_method=anchor_method,
            error=f"missing_{network.replace('-', '_')}_credentials",
        )

    try:
        from eth_account import Account
        from web3 import Web3
    except Exception as exc:
        return build_anchor_record_pending(
            root_hash,
            network=network,
            wallet_address=wallet_address,
            anchor_method=anchor_method,
            error=f"web3_not_available:{exc}",
        )

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url.strip()))
        if not w3.is_connected():
            return build_anchor_record_pending(
                root_hash,
                network=network,
                wallet_address=wallet_address,
                anchor_method=anchor_method,
                error="rpc_not_connected",
            )
        chain_id = w3.eth.chain_id
        if chain_id != expected_chain_id:
            return build_anchor_record_pending(
                root_hash,
                network=network,
                wallet_address=wallet_address,
                anchor_method=anchor_method,
                error=f"unexpected_chain_id:{chain_id}",
            )

        acct = Account.from_key(private_key.strip())
        from_checksum = Web3.to_checksum_address(from_address.strip())
        if acct.address.lower() != from_checksum.lower():
            return build_anchor_record_pending(
                root_hash,
                network=network,
                wallet_address=from_checksum,
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
                    return build_anchor_record_pending(
                        root_hash,
                        network=network,
                        wallet_address=from_checksum,
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
                return build_blockchain_anchor_record(
                    root_hash,
                    network=network,
                    anchor_method=anchor_method,
                    transaction_reference=tx_hash_hex,
                    status="anchored",
                    block_number=receipt.blockNumber,
                    wallet_address=from_checksum,
                    explorer_url=f"{explorer_base_url.rstrip('/')}/{tx_hash_hex}",
                )
            except Exception as exc:
                if attempt < 2 and _is_retryable_anchor_error(exc):
                    sleep(1)
                    continue
                raise
    except Exception as exc:
        return build_anchor_record_pending(
            root_hash,
            network=network,
            wallet_address=wallet_address,
            anchor_method=anchor_method,
            error=f"anchor_exception:{exc}",
        )


def anchor_eb1_root(root_hash: str, network: str | None = None) -> dict[str, Any]:
    resolved = (network or settings.hrevn_eb_anchor_network or "base").strip().lower()
    anchor_method = settings.hrevn_eb_anchor_method or "hrevn_managed_anchor"

    if resolved == "sepolia":
        return anchor_root_on_evm(
            root_hash,
            network="sepolia",
            rpc_url=settings.hrevn_start_sepolia_rpc_url,
            private_key=settings.hrevn_start_sepolia_private_key,
            from_address=settings.hrevn_start_sepolia_from_address,
            expected_chain_id=11155111,
            explorer_base_url=settings.hrevn_start_anchor_explorer_base_url,
            wait_confirmations=settings.hrevn_start_sepolia_wait_confirmations,
            anchor_method=anchor_method,
        )
    if resolved == "base-sepolia":
        return anchor_root_on_evm(
            root_hash,
            network="base-sepolia",
            rpc_url=settings.hrevn_eb_base_sepolia_rpc_url,
            private_key=settings.hrevn_eb_base_sepolia_private_key,
            from_address=settings.hrevn_eb_base_sepolia_from_address,
            expected_chain_id=84532,
            explorer_base_url=settings.hrevn_eb_base_sepolia_explorer_base_url,
            wait_confirmations=settings.hrevn_eb_base_sepolia_wait_confirmations,
            anchor_method=anchor_method,
        )
    if resolved == "base":
        return anchor_root_on_evm(
            root_hash,
            network="base",
            rpc_url=settings.hrevn_eb_base_rpc_url,
            private_key=settings.hrevn_eb_base_private_key,
            from_address=settings.hrevn_eb_base_from_address,
            expected_chain_id=8453,
            explorer_base_url=settings.hrevn_eb_base_explorer_base_url or settings.hrevn_eb_anchor_explorer_base_url,
            wait_confirmations=settings.hrevn_eb_base_wait_confirmations,
            anchor_method=anchor_method,
        )
    return build_anchor_record_pending(
        root_hash,
        network=resolved or "unknown",
        anchor_method=anchor_method,
        error=f"unsupported_anchor_network:{resolved}",
    )


def manifest_anchor_status(anchor_record: dict[str, Any]) -> str:
    status = anchor_record.get("status")
    if status == "anchored":
        return "anchored"
    if status == "anchor_failed":
        return "anchor_failed"
    return "anchor_pending"
