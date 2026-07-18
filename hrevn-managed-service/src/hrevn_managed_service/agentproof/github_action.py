from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .repository_verify import (
    AgentProofRepositoryVerifyError,
    verify_repository_state,
)
from .seal import AgentProofSealError, load_canonical_receipt, seal_receipt


_MAX_BUNDLE_BYTES = 50 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMMENT_MARKER = "<!-- hrevn-agentproof -->"


class AgentProofActionError(RuntimeError):
    pass


def _download_bytes(
    url: str,
    *,
    max_bytes: int = _MAX_BUNDLE_BYTES,
    opener: Callable[..., Any] = urlopen,
) -> bytes:
    request = Request(url, headers={"Accept": "application/octet-stream"}, method="GET")
    try:
        with opener(request, timeout=90) as response:
            content = response.read(max_bytes + 1)
    except HTTPError as exc:
        raise AgentProofActionError(f"artifact_download_http_error:{exc.code}") from exc
    except (URLError, OSError) as exc:
        raise AgentProofActionError("artifact_download_failed") from exc
    if len(content) > max_bytes:
        raise AgentProofActionError("artifact_download_too_large")
    return content


def _relative_workspace_path(value: str | Path, workspace: Path) -> Path:
    root = workspace.expanduser().resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AgentProofActionError("path_outside_workspace") from exc
    return candidate


def _anchor_explorer_url(network: str | None, transaction_reference: str | None) -> str | None:
    if not transaction_reference:
        return None
    normalized_network = (network or "").lower()
    if "sepolia" in normalized_network:
        return f"https://sepolia.etherscan.io/tx/{transaction_reference}"
    return None


def _public_result(
    repository_verification: dict[str, Any],
    seal_response: dict[str, Any],
) -> dict[str, Any]:
    metadata = seal_response["metadata"]
    anchor = metadata.get("anchor") or {}
    transaction_reference = anchor.get("transaction_reference")
    return {
        "result": "AGENT_VERIFIED",
        "repository_verification": {
            key: value
            for key, value in repository_verification.items()
            if key != "repository_root"
        },
        "bundle": {
            "bundle_id": seal_response["bundle_id"],
            "root_hash": metadata["root_hash"],
            "signature_status": metadata["signature_status"],
            "signature_algorithm": metadata.get("signature_algorithm"),
            "signature_public_key_id": metadata.get("signature_public_key_id"),
            "anchor_status": metadata["anchor_status"],
            "anchor_network": anchor.get("network"),
            "transaction_reference": transaction_reference,
            "transaction_explorer_url": _anchor_explorer_url(
                anchor.get("network"), transaction_reference
            ),
            "verification_url": metadata.get("verification_url"),
            "download_url": seal_response["public_download_url"],
            "sha256_url": seal_response["public_sha256_url"],
        },
    }


def build_pull_request_comment(
    result: dict[str, Any],
    *,
    artifact_url: str | None = None,
) -> str:
    bundle = result["bundle"]
    repository = result["repository_verification"]
    transaction = bundle.get("transaction_reference") or "pending"
    transaction_url = bundle.get("transaction_explorer_url")
    transaction_markdown = (
        f"[`{transaction}`]({transaction_url})" if transaction_url else f"`{transaction}`"
    )
    links = [f"[Verify bundle]({bundle['verification_url']})"]
    links.append(f"[Download EB1]({bundle['download_url']})")
    if artifact_url:
        links.append(f"[Workflow artifact]({artifact_url})")
    return "\n".join(
        (
            _COMMENT_MARKER,
            "## Agent-verified",
            "",
            f"**Evidence Bundle `{bundle['bundle_id']}`** was generated after the committed "
            "repository state matched the canonical AgentProof receipt.",
            "",
            "| Check | Result |",
            "| --- | --- |",
            f"| Repository commitments | **{repository['result']}** "
            f"({repository['checked_file_count']} files) |",
            f"| Ed25519 signature | **{bundle['signature_status']}** |",
            f"| Sepolia anchor | **{bundle['anchor_status']}** |",
            f"| Transaction | {transaction_markdown} |",
            "",
            " · ".join(links),
            "",
            "> AgentProof is tamper-evident, not exhaustive: it proves the integrity of "
            "events observed by the instrumented collector.",
        )
    )


def verify_seal_and_export(
    *,
    receipt_path: Path,
    repository_path: Path,
    result_directory: Path,
    api_base_url: str,
    api_key: str,
    allow_pending: bool = False,
    sealer: Callable[..., dict[str, Any]] = seal_receipt,
    downloader: Callable[[str], bytes] = _download_bytes,
) -> dict[str, Any]:
    if not api_key:
        raise AgentProofActionError("api_key_missing")
    receipt, receipt_bytes = load_canonical_receipt(receipt_path)
    repository_verification = verify_repository_state(receipt, repository_path)
    if not repository_verification["valid"]:
        paths = ",".join(item["path"] for item in repository_verification["mismatches"])
        raise AgentProofActionError(f"repository_state_mismatch:{paths}")

    seal_response = sealer(
        receipt_path,
        api_base_url=api_base_url,
        api_key=api_key,
        allow_pending=allow_pending,
    )
    result = _public_result(repository_verification, seal_response)
    bundle = result["bundle"]
    bundle_bytes = downloader(bundle["download_url"])
    sidecar_bytes = downloader(bundle["sha256_url"])
    try:
        declared_hash = sidecar_bytes.decode("utf-8").strip().split()[0].lower()
    except (UnicodeDecodeError, IndexError) as exc:
        raise AgentProofActionError("bundle_sidecar_invalid") from exc
    actual_hash = hashlib.sha256(bundle_bytes).hexdigest()
    if not _SHA256_RE.fullmatch(declared_hash) or declared_hash != actual_hash:
        raise AgentProofActionError("bundle_sidecar_mismatch")
    bundle["zip_sha256"] = actual_hash

    output = result_directory.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    bundle_name = f"{bundle['bundle_id']}.zip"
    (output / bundle_name).write_bytes(bundle_bytes)
    (output / f"{bundle_name}.sha256").write_text(
        f"{actual_hash}  {bundle_name}\n", encoding="utf-8"
    )
    (output / "agent-session.json").write_bytes(receipt_bytes)
    (output / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "pull-request-comment.md").write_text(
        build_pull_request_comment(result) + "\n", encoding="utf-8"
    )
    return result


def _github_request(
    *,
    url: str,
    token: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    opener: Callable[..., Any] = urlopen,
) -> Any:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with opener(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise AgentProofActionError(f"github_api_http_error:{exc.code}") from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise AgentProofActionError("github_api_invalid_response") from exc


def publish_pull_request_comment(
    *,
    result: dict[str, Any],
    token: str,
    repository: str,
    pull_request_number: int,
    artifact_url: str | None = None,
    api_url: str = "https://api.github.com",
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    if not token:
        raise AgentProofActionError("github_token_missing")
    if not _REPOSITORY_RE.fullmatch(repository):
        raise AgentProofActionError("github_repository_invalid")
    body = build_pull_request_comment(result, artifact_url=artifact_url)
    repository_path = quote(repository, safe="/")
    comments_url = (
        f"{api_url.rstrip('/')}/repos/{repository_path}/issues/"
        f"{pull_request_number}/comments?per_page=100"
    )
    comments = _github_request(url=comments_url, token=token, opener=opener)
    if not isinstance(comments, list):
        raise AgentProofActionError("github_comments_invalid")
    existing = next(
        (
            item
            for item in comments
            if isinstance(item, dict)
            and isinstance(item.get("body"), str)
            and _COMMENT_MARKER in item["body"]
        ),
        None,
    )
    if existing:
        comment_id = existing.get("id")
        if not isinstance(comment_id, int):
            raise AgentProofActionError("github_comment_id_invalid")
        response = _github_request(
            url=f"{api_url.rstrip('/')}/repos/{repository_path}/issues/comments/{comment_id}",
            token=token,
            method="PATCH",
            payload={"body": body},
            opener=opener,
        )
        action = "updated"
    else:
        response = _github_request(
            url=comments_url.split("?", 1)[0],
            token=token,
            method="POST",
            payload={"body": body},
            opener=opener,
        )
        action = "created"
    return {"action": action, "comment_url": response.get("html_url")}


def _write_github_outputs(path: Path, values: dict[str, str | None]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            if value is None:
                continue
            if "\n" in value or "\r" in value:
                raise AgentProofActionError("github_output_multiline_not_allowed")
            output.write(f"{key}={value}\n")


def _pull_request_number(event_path: Path) -> int:
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        number = event["pull_request"]["number"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AgentProofActionError("github_pull_request_event_invalid") from exc
    if not isinstance(number, int) or number < 1:
        raise AgentProofActionError("github_pull_request_number_invalid")
    return number


def _run_action(args: argparse.Namespace) -> None:
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
    receipt = _relative_workspace_path(args.receipt, workspace)
    repository = _relative_workspace_path(args.repository, workspace)
    result_directory = _relative_workspace_path(args.result_directory, workspace)
    result = verify_seal_and_export(
        receipt_path=receipt,
        repository_path=repository,
        result_directory=result_directory,
        api_base_url=args.api_url,
        api_key=os.environ.get("HREVN_AGENTPROOF_API_KEY", ""),
        allow_pending=args.allow_pending,
    )
    result_path = result_directory / "result.json"
    bundle = result["bundle"]
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        _write_github_outputs(
            Path(github_output),
            {
                "bundle-id": bundle["bundle_id"],
                "verification-url": bundle["verification_url"],
                "transaction-reference": bundle["transaction_reference"],
                "result-directory": str(result_directory),
                "result-json": str(result_path),
            },
        )
    print(
        json.dumps(
            {
                "result": result["result"],
                "bundle_id": bundle["bundle_id"],
                "anchor_status": bundle["anchor_status"],
            },
            sort_keys=True,
        )
    )


def _comment_action(args: argparse.Namespace) -> None:
    try:
        result = json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentProofActionError("action_result_unreadable") from exc
    response = publish_pull_request_comment(
        result=result,
        token=os.environ.get("GITHUB_TOKEN", ""),
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        pull_request_number=_pull_request_number(Path(os.environ.get("GITHUB_EVENT_PATH", ""))),
        artifact_url=args.artifact_url,
        api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )
    print(json.dumps(response, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AgentProof inside GitHub Actions.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--receipt", required=True)
    run_parser.add_argument("--repository", default=".")
    run_parser.add_argument("--result-directory", default="agentproof-action-result")
    run_parser.add_argument("--api-url", default="https://agentproof.hrevn.com/api")
    run_parser.add_argument("--allow-pending", action="store_true")
    comment_parser = subparsers.add_parser("comment")
    comment_parser.add_argument("--result-json", required=True)
    comment_parser.add_argument("--artifact-url")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "run":
            _run_action(args)
        else:
            _comment_action(args)
    except (AgentProofActionError, AgentProofRepositoryVerifyError, AgentProofSealError) as exc:
        raise SystemExit(f"AgentProof Action failed: {exc}") from exc


if __name__ == "__main__":
    main()
