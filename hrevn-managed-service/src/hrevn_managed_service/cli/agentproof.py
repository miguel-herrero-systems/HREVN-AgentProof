from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ..agentproof.codex_capture import capture_codex_session
from ..agentproof.repository_verify import AgentProofRepositoryVerifyError, verify_repository_state
from ..agentproof.seal import AgentProofSealError, seal_receipt
from ..agentproof.seal import load_canonical_receipt


def _print_progress(event: dict) -> None:
    if event.get("type") != "item.completed":
        return
    item = event.get("item") or {}
    if item.get("type") == "command_execution":
        print(f"command captured · exit {item.get('exit_code')}")
    elif item.get("type") == "agent_message" and item.get("text"):
        print(item["text"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hrevn-agentproof",
        description="Capture and seal privacy-preserving AgentProof session receipts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run Codex CLI and emit a canonical session receipt.")
    run_parser.add_argument("--repo", type=Path, default=Path.cwd())
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--sandbox", default="workspace-write", choices=("read-only", "workspace-write"))
    run_parser.add_argument("prompt")

    seal_parser = subparsers.add_parser("seal", help="Seal a canonical receipt as a signed EB1 bundle.")
    seal_parser.add_argument("--receipt", type=Path, required=True)
    seal_parser.add_argument("--api-url", default="https://api.hrevn.com")
    seal_parser.add_argument("--api-key-env", default="HREVN_API_KEY")
    seal_parser.add_argument("--allow-pending", action="store_true")
    seal_parser.add_argument("--timeout", type=float, default=90)

    verify_parser = subparsers.add_parser(
        "verify-repo",
        help="Compare the receipt's final file commitments with a local repository.",
    )
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--repo", type=Path, default=Path.cwd())
    return parser


def _run_command(args: argparse.Namespace) -> None:
    receipt = capture_codex_session(
        repo=args.repo,
        prompt=args.prompt,
        output_path=args.output,
        model=args.model,
        sandbox=args.sandbox,
        on_item=_print_progress,
    )
    print(
        json.dumps(
            {
                "session_id": receipt["session_id"],
                "event_count": receipt["event_count"],
                "chain_head_sha256": receipt["chain_head_sha256"],
                "receipt": str(args.output.expanduser().resolve()),
            },
            sort_keys=True,
        )
    )


def _seal_command(args: argparse.Namespace) -> None:
    api_key = os.getenv(args.api_key_env) if args.api_key_env else None
    response = seal_receipt(
        args.receipt,
        api_base_url=args.api_url,
        api_key=api_key,
        allow_pending=args.allow_pending,
        timeout_seconds=args.timeout,
    )
    metadata = response["metadata"]
    anchor = metadata.get("anchor") or {}
    print(
        json.dumps(
            {
                "bundle_id": response["bundle_id"],
                "root_hash": metadata["root_hash"],
                "signature_status": metadata["signature_status"],
                "anchor_status": metadata["anchor_status"],
                "transaction_reference": anchor.get("transaction_reference"),
                "verification_url": metadata.get("verification_url"),
                "download_url": response["public_download_url"],
                "sha256_url": response["public_sha256_url"],
            },
            sort_keys=True,
        )
    )


def _verify_repository_command(args: argparse.Namespace) -> None:
    receipt, _receipt_bytes = load_canonical_receipt(args.receipt)
    result = verify_repository_state(receipt, args.repo)
    print(json.dumps(result, sort_keys=True))
    if not result["valid"]:
        raise SystemExit(1)


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "run":
            _run_command(args)
        elif args.command == "seal":
            _seal_command(args)
        else:
            _verify_repository_command(args)
    except (AgentProofSealError, AgentProofRepositoryVerifyError) as exc:
        raise SystemExit(f"AgentProof failed: {exc}") from exc


if __name__ == "__main__":
    main()
