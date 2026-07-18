from __future__ import annotations

from typing import Any


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _profile(metadata: dict[str, Any], manifest: dict[str, Any]) -> str:
    return _text(metadata.get("profile")) or _text(manifest.get("package_type")) or "generic_evidence_bundle"


def _package_title(metadata: dict[str, Any], manifest: dict[str, Any]) -> str:
    return _text(metadata.get("package_title")) or _text(manifest.get("title")) or "HREVN Evidence Bundle"


def _issued_at(metadata: dict[str, Any], manifest: dict[str, Any]) -> str:
    return _text(metadata.get("issued_at")) or _text(manifest.get("generated_at_utc")) or "unknown"


def build_eb1_readme_text(metadata: dict[str, Any], manifest: dict[str, Any]) -> str:
    profile = _profile(metadata, manifest)
    package_title = _package_title(metadata, manifest)
    package_summary = _text(metadata.get("package_summary")) or "Document package sealed for later integrity verification."
    issued_at = _issued_at(metadata, manifest)

    return (
        f"HREVN Evidence Bundle\n"
        f"Title: {package_title}\n"
        f"Profile: {profile}\n"
        f"Issued at: {issued_at}\n\n"
        f"Summary:\n"
        f"{package_summary}\n\n"
        f"This bundle preserves the original package as issued.\n"
        f"It helps a third party verify whether the files in this package still match the original set.\n"
        f"HREVN does not certify material truth, authorship, legality, or technical correctness of the underlying documents.\n"
    )


def build_eb1_protocol_version_text(manifest: dict[str, Any]) -> str:
    return (
        "HREVN Evidence Bundle Protocol\n"
        f"Bundle profile: {_text(manifest.get('bundle_profile')) or 'evidence_bundle_eb1_v1'}\n"
        f"Package family: {_text(manifest.get('package_family')) or 'hrevn_evidence_bundle'}\n"
        f"Package type: {_text(manifest.get('package_type')) or 'generic_evidence_bundle'}\n"
        "Root specification: ROOT_SPEC_EB1.txt\n"
        "Root algorithm: HREVN_ROOT_EB1_V1\n"
    )


def build_eb1_verification_text(
    metadata: dict[str, Any],
    manifest: dict[str, Any],
    anchor_status: str = "anchor_pending",
    anchor_network: str | None = None,
    anchor_transaction_reference: str | None = None,
    anchor_explorer_url: str | None = None,
    signature_status: str = "unsigned",
    signature_algorithm: str | None = None,
    signature_public_key_id: str | None = None,
) -> str:
    package_title = _package_title(metadata, manifest)
    issued_at = _issued_at(metadata, manifest)
    profile = _profile(metadata, manifest)
    lines = [
        "Verification summary\n",
        f"Package: {package_title}\n",
        f"Profile: {profile}\n",
        f"Issued at: {issued_at}\n",
        f"Authoritative files: {len(manifest.get('authoritative_files', []))}\n",
        "Root source: manifest.authoritative_files\n",
        "Root spec file: ROOT_SPEC_EB1.txt\n",
        f"Signature status: {signature_status}\n",
    ]
    if signature_algorithm:
        lines.append(f"Signature algorithm: {signature_algorithm}\n")
    if signature_public_key_id:
        lines.append(f"Signature key id: {signature_public_key_id}\n")
    if anchor_network:
        lines.append(f"Anchor network: {anchor_network}\n")
    if anchor_transaction_reference:
        lines.append(f"Anchor reference: {anchor_transaction_reference}\n")
    if anchor_explorer_url:
        lines.append(f"Anchor explorer: {anchor_explorer_url}\n")
    lines.extend(
        [
            f"Blockchain anchor status: {anchor_status}\n\n",
            "If any authoritative file changes later, its hash changes and the package verification will detect the difference.\n",
        ]
    )
    return "".join(lines)


def build_eb1_how_to_verify_text(metadata: dict[str, Any], manifest: dict[str, Any]) -> str:
    package_title = _package_title(metadata, manifest)
    return (
        f"How to verify this package: {package_title}\n\n"
        "This package is designed so an independent auditor or AI agent can verify it without querying HREVN private systems.\n\n"
        "1. Unzip the package into a temporary folder. Reject paths that are absolute or contain '..'. Do not execute or render files; read bytes only.\n"
        "2. Read CHECKSUMS.sha256. For every listed file, compute SHA-256 over the exact bytes and compare it with the declared hash.\n"
        "3. Open manifest.json and read authoritative_files. These are the files that define the EB1 evidentiary root.\n"
        "4. For each authoritative file, compute SHA-256 and build the root serialization described in ROOT_SPEC_EB1.txt:\n"
        "   relative_path:sha256hex, sorted by ascending ASCII relative_path, joined with LF, with no trailing LF.\n"
        "5. Compute SHA-256 over that UTF-8 serialization. This is the recalculated EB1 root. Compare it with ROOT_HASH_SHA256.txt.\n"
        "6. Open SIGNATURE_ED25519.json. Decode public_key_b64 and signature_b64 from Base64. Verify the Ed25519 signature over bytes.fromhex(root_hash).\n"
        "7. Confirm that SIGNATURE_ED25519.json root_hash equals ROOT_HASH_SHA256.txt. If the signature is valid for a different root, report that precisely.\n"
        "8. Open BLOCKCHAIN_ANCHOR.json. Confirm status, network, transaction_reference and root_hash. The anchor root_hash must equal ROOT_HASH_SHA256.txt.\n"
        "9. If network is sepolia and explorer_url is present, open the public transaction and confirm the recorded on-chain reference corresponds to this root.\n"
        "10. Verdict guidance: if checksums, root, signature and anchor all match, the package is intact. If the signature is valid for the sealed root but the files reproduce a different root, the package was modified after sealing.\n"
    )


def build_eb1_human_files(
    metadata: dict[str, Any],
    manifest: dict[str, Any],
    anchor_status: str = "anchor_pending",
    anchor_network: str | None = None,
    anchor_transaction_reference: str | None = None,
    anchor_explorer_url: str | None = None,
    signature_status: str = "unsigned",
    signature_algorithm: str | None = None,
    signature_public_key_id: str | None = None,
) -> dict[str, str]:
    return {
        "README.txt": build_eb1_readme_text(metadata, manifest),
        "PROTOCOL_VERSION.txt": build_eb1_protocol_version_text(manifest),
        "VERIFICATION.txt": build_eb1_verification_text(
            metadata,
            manifest,
            anchor_status=anchor_status,
            anchor_network=anchor_network,
            anchor_transaction_reference=anchor_transaction_reference,
            anchor_explorer_url=anchor_explorer_url,
            signature_status=signature_status,
            signature_algorithm=signature_algorithm,
            signature_public_key_id=signature_public_key_id,
        ),
        "HOW_TO_VERIFY_THIS_PACKAGE.txt": build_eb1_how_to_verify_text(metadata, manifest),
    }
