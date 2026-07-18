from __future__ import annotations

import json
from pathlib import Path
import sys
import zipfile
from base64 import b64decode

from cryptography.hazmat.primitives.asymmetric import ed25519

from .generator_adapter import build_eb1_checksums, build_eb1_root_hash, _sha256_hex

from ..config import settings


def _ensure_verifier_path() -> None:
    plugin_root = str(Path(settings.verifier_plugin_root))
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)


def _zip_logical_files(path: Path) -> tuple[dict[str, bytes], str]:
    with zipfile.ZipFile(path) as zf:
        members = [name for name in zf.namelist() if not name.endswith("/")]
        manifest_members = [name for name in members if name.endswith("manifest.json")]
        if not manifest_members:
            return {}, ""

        manifest_member = manifest_members[0]
        outer_prefix = manifest_member[: -len("manifest.json")]

        logical_files: dict[str, bytes] = {}
        for member in members:
            if outer_prefix and member.startswith(outer_prefix):
                logical_name = member[len(outer_prefix) :]
            else:
                logical_name = member
            logical_files[logical_name] = zf.read(member)

    return logical_files, outer_prefix


def _parse_checksums(checksums_text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in checksums_text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            parsed[parts[1].strip()] = parts[0].strip()
    return parsed


def _looks_like_eb1_manifest(manifest: dict) -> bool:
    if manifest.get("root_hash_algorithm") == "HREVN_ROOT_EB1_V1":
        return True
    bundle_profile = manifest.get("bundle_profile")
    return bundle_profile in {"evidence_bundle_eb1_v1", "evidence_bundle_ai_document_integrity_v1"}


def _verify_eb1_bundle(path: Path) -> dict | None:
    if not path.exists() or not zipfile.is_zipfile(path):
        return None

    logical_files, _outer_prefix = _zip_logical_files(path)
    manifest_bytes = logical_files.get("manifest.json")
    if not manifest_bytes:
        return None

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if not _looks_like_eb1_manifest(manifest):
        return None

    checksums_text = logical_files.get("CHECKSUMS.sha256", b"").decode("utf-8")
    declared_checksums = _parse_checksums(checksums_text)

    passed: list[str] = []
    failed: list[dict] = []
    missing: list[str] = []
    unchecked: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    for relative_path, declared_hash in declared_checksums.items():
        content = logical_files.get(relative_path)
        if content is None:
            missing.append(relative_path)
            errors.append(f"missing_file: {relative_path}")
            continue
        computed_hash = _sha256_hex(content)
        if computed_hash != declared_hash:
            failed.append(
                {
                    "file": relative_path,
                    "declared": declared_hash,
                    "computed": computed_hash,
                }
            )
            errors.append(f"checksum_mismatch: {relative_path}")
        else:
            passed.append(relative_path)

    for relative_path in sorted(name for name in logical_files if name != "CHECKSUMS.sha256" and name not in declared_checksums):
        unchecked.append(relative_path)
        warnings.append(f"unchecked_file: {relative_path}")

    root_declared = logical_files.get("ROOT_HASH_SHA256.txt", b"").decode("utf-8").strip()
    root_computed = ""
    root_match = False
    try:
        root_computed = build_eb1_root_hash(logical_files, manifest.get("authoritative_files", []))
        root_match = bool(root_declared) and root_declared == root_computed
        if not root_match:
            errors.append("root_hash_mismatch: computed hash does not match declared")
    except ValueError as exc:
        errors.append(str(exc))

    checksums_canonical_match = checksums_text == build_eb1_checksums(logical_files)
    checksums_match = not failed and not missing
    if not checksums_match and "CHECKSUMS.sha256" not in logical_files:
        errors.append("missing_file: CHECKSUMS.sha256")
    elif checksums_match and not checksums_canonical_match:
        warnings.append("checksums_noncanonical_order")

    anchor_data = None
    if "BLOCKCHAIN_ANCHOR.json" in logical_files:
        try:
            anchor_data = json.loads(logical_files["BLOCKCHAIN_ANCHOR.json"].decode("utf-8"))
        except json.JSONDecodeError:
            warnings.append("anchor_unreadable")

    anchor_status = manifest.get("external_anchor_status") or (anchor_data or {}).get("status")
    if anchor_status == "anchor_failed":
        warnings.append("anchor_failed")
    elif anchor_status == "anchor_pending":
        warnings.append("anchor_pending")
    elif not anchor_status:
        warnings.append("not_anchored")

    signature_data = None
    signature_valid: bool | None = None
    signature_status = manifest.get("signature_status") or "unsigned"
    if "SIGNATURE_ED25519.json" in logical_files:
        try:
            signature_data = json.loads(logical_files["SIGNATURE_ED25519.json"].decode("utf-8"))
            signature_root_hash = str(signature_data.get("root_hash") or "").strip()
            signature_b64 = str(signature_data.get("signature_b64") or "").strip()
            public_key_b64 = str(signature_data.get("public_key_b64") or "").strip()
            signature_status = str(signature_data.get("status") or signature_status)
            if signature_status == "signed" and signature_root_hash and signature_b64 and public_key_b64:
                public_key = ed25519.Ed25519PublicKey.from_public_bytes(b64decode(public_key_b64))
                public_key.verify(b64decode(signature_b64), bytes.fromhex(signature_root_hash))
                signature_valid = signature_root_hash == root_declared
                if not signature_valid:
                    warnings.append("signature_root_hash_mismatch")
            elif signature_status == "signed":
                signature_valid = False
                warnings.append("signature_incomplete")
            elif signature_status == "signing_not_configured":
                warnings.append("signature_not_configured")
            elif signature_status == "signing_failed":
                warnings.append("signature_failed")
        except Exception:
            signature_valid = False
            warnings.append("signature_invalid")
    else:
        if signature_status == "signed":
            signature_valid = False
            warnings.append("signature_missing")
        elif signature_status == "signing_not_configured":
            warnings.append("signature_not_configured")

    return {
        "tool": "verify_bundle",
        "source": str(path),
        "valid": not errors and checksums_match and root_match,
        "errors": errors,
        "warnings": warnings,
        "schema_version": manifest.get("bundle_profile"),
        "package_type": manifest.get("package_type"),
        "manifest_hash": _sha256_hex(manifest_bytes),
        "root_hash_declared": root_declared or None,
        "root_hash_computed": root_computed or None,
        "root_hash_match": root_match,
        "anchor": anchor_data,
        "signature_status": signature_status,
        "signature_valid": signature_valid,
        "signature_algorithm": (signature_data or {}).get("algorithm") or manifest.get("signature_algorithm"),
        "signature_public_key_id": (signature_data or {}).get("public_key_id") or manifest.get("signature_public_key_id"),
        "checksums": {
            "valid": not failed and not missing,
            "passed": passed,
            "failed": failed,
            "missing": missing,
            "unchecked": unchecked,
        },
        "artifact_count": manifest.get("artifact_count"),
        "aer_id": manifest.get("record_id") or manifest.get("aer_id"),
    }


def run_verify_bundle(source: str) -> dict:
    path = Path(source).expanduser().resolve()
    native_eb1 = _verify_eb1_bundle(path)
    if native_eb1 is not None:
        return native_eb1

    _ensure_verifier_path()
    from tools import verify_bundle

    return verify_bundle(source)
