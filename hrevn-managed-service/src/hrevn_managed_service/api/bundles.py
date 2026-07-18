from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..models.auth_models import AuthContext
from ..models.requests import GenerateBundleRequest, VerifyBundleRequest
from ..models.responses import (
    BlockchainAnchorResponse,
    GenerateBundleMetadataResponse,
    GenerateBundleResponse,
    VerifyBundleResponse,
)
from ..services.auth import resolve_auth_context
from ..services.bundle_service import create_bundle, resolve_bundle_download, verify_bundle_source


router = APIRouter(tags=["bundles"])

MAX_AUDIT_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_AUDIT_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_AUDIT_ZIP_FILES = 250
AUDIT_RATE_LIMIT_WINDOW_SECONDS = 60
AUDIT_RATE_LIMIT_MAX_REQUESTS = 12
_audit_rate_limit: dict[str, list[float]] = {}


def _public_verify_url(bundle_id: str) -> str:
    return f"https://hrevn.com/verify/evidence-bundle/?bundle_id={bundle_id}"


@router.post("/v1/verify-bundle", response_model=VerifyBundleResponse)
def verify_bundle(request: VerifyBundleRequest, _auth: AuthContext = Depends(resolve_auth_context)) -> VerifyBundleResponse:
    result = verify_bundle_source(request.source)
    if result.get("anchor"):
        result["anchor"] = BlockchainAnchorResponse(**result["anchor"])
    return VerifyBundleResponse(**result)


@router.post("/v1/generate-bundle", response_model=GenerateBundleResponse)
def generate_bundle_endpoint(
    request: GenerateBundleRequest, _auth: AuthContext = Depends(resolve_auth_context)
) -> GenerateBundleResponse:
    created = create_bundle(record=request.record, traces=request.traces, bundle_mode=request.bundle_mode)
    return GenerateBundleResponse(
        bundle_id=created["bundle_id"],
        download_url=f"/v1/bundles/{created['bundle_id']}/download",
        expires_at=created["expires_at"],
        metadata=GenerateBundleMetadataResponse(
            record_id=created["record_id"],
            verification_url=_public_verify_url(created["bundle_id"]),
            schema_version=created["schema_version"],
            bundle_mode=created.get("bundle_mode"),
            bundle_profile=created.get("bundle_profile"),
            package_type=created.get("package_type"),
            root_hash=created.get("root_hash"),
            anchor_status=created.get("anchor_status"),
            anchor=BlockchainAnchorResponse(**created["anchor"]) if created.get("anchor") else None,
            signature_status=created.get("signature_status"),
            signature_algorithm=created.get("signature_algorithm"),
            signature_public_key_id=created.get("signature_public_key_id"),
            warnings=created.get("warnings", []),
        ),
    )


@router.get("/v1/public/bundles/{bundle_id}/verify-record", response_model=VerifyBundleResponse)
def public_verify_bundle_record(bundle_id: str) -> VerifyBundleResponse:
    path = Path(resolve_bundle_download(bundle_id))
    result = verify_bundle_source(str(path))
    if result.get("anchor"):
        result["anchor"] = BlockchainAnchorResponse(**result["anchor"])
    result["source"] = bundle_id
    return VerifyBundleResponse(**result)


@router.get("/v1/public/bundles/{bundle_id}/download")
def public_download_bundle(bundle_id: str):
    path = resolve_bundle_download(bundle_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/v1/public/bundles/{bundle_id}/sha256")
def public_bundle_sha256(bundle_id: str) -> Response:
    path = Path(resolve_bundle_download(bundle_id))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    body = f"{digest}  {path.name}\n"
    return Response(
        body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{path.name}.sha256"'},
    )


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_audit_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    now = time.monotonic()
    recent = [ts for ts in _audit_rate_limit.get(ip, []) if now - ts < AUDIT_RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= AUDIT_RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(status_code=429, detail={"error_code": "audit_rate_limited"})
    recent.append(now)
    _audit_rate_limit[ip] = recent


async def _store_limited_upload(request: Request, tmp_dir: Path) -> Path:
    target = tmp_dir / "uploaded_bundle.zip"
    size = 0
    with target.open("wb") as handle:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_AUDIT_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail={"error_code": "audit_zip_too_large", "limit_mb": 50})
            handle.write(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail={"error_code": "audit_empty_upload"})
    return target


def _validate_safe_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise HTTPException(status_code=400, detail={"error_code": "audit_not_a_zip"})

    try:
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
            files = [item for item in members if not item.is_dir()]
            if len(files) > MAX_AUDIT_ZIP_FILES:
                raise HTTPException(status_code=400, detail={"error_code": "audit_too_many_files"})

            uncompressed_total = 0
            for item in members:
                name = item.filename
                pure = PurePosixPath(name)
                if (
                    not name
                    or name.startswith("/")
                    or "\\" in name
                    or ":" in pure.parts[0]
                    or any(part in {"", ".", ".."} for part in pure.parts)
                ):
                    raise HTTPException(status_code=400, detail={"error_code": "audit_unsafe_zip_path", "path": name})
                uncompressed_total += item.file_size
                if uncompressed_total > MAX_AUDIT_UNCOMPRESSED_BYTES:
                    raise HTTPException(status_code=400, detail={"error_code": "audit_zip_uncompressed_too_large"})
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail={"error_code": "audit_not_a_zip"}) from exc


def _logical_files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        manifest_members = [name for name in names if name.endswith("manifest.json")]
        outer_prefix = manifest_members[0][: -len("manifest.json")] if manifest_members else ""
        files: dict[str, bytes] = {}
        for name in names:
            logical = name[len(outer_prefix) :] if outer_prefix and name.startswith(outer_prefix) else name
            files[logical] = zf.read(name)
    return files


def _read_json_file(files: dict[str, bytes], name: str) -> dict[str, Any] | None:
    raw = files.get(name)
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _origin_check(bundle_id: str | None, sealed_root: str | None) -> dict[str, Any]:
    if not bundle_id:
        return {"emitted_by_hrevn": False, "bundle_id": None, "registered_root_hash": None}
    try:
        registered_path = Path(resolve_bundle_download(bundle_id))
        registered = verify_bundle_source(str(registered_path))
    except Exception:
        return {"emitted_by_hrevn": False, "bundle_id": bundle_id, "registered_root_hash": None}

    registered_root = registered.get("root_hash_declared")
    return {
        "emitted_by_hrevn": bool(registered_root and sealed_root and registered_root == sealed_root),
        "bundle_id": bundle_id,
        "registered_root_hash": registered_root,
    }


def _signature_root(files: dict[str, bytes]) -> str | None:
    signature = _read_json_file(files, "SIGNATURE_ED25519.json") or {}
    root = signature.get("root_hash")
    return root if isinstance(root, str) and root else None


def _anchor_summary(anchor: dict[str, Any] | None, sealed_root: str | None) -> dict[str, Any]:
    anchor = anchor or {}
    root_hash = anchor.get("root_hash")
    return {
        "status": anchor.get("status"),
        "network": anchor.get("network"),
        "transaction_reference": anchor.get("transaction_reference"),
        "block_number": anchor.get("block_number"),
        "explorer_url": anchor.get("explorer_url"),
        "root_hash": root_hash,
        "root_matches_sealed": bool(root_hash and sealed_root and root_hash == sealed_root),
    }


def _audit_payload(path: Path) -> dict[str, Any]:
    files = _logical_files(path)
    manifest = _read_json_file(files, "manifest.json") or {}
    signature_root = _signature_root(files)

    try:
        verification = verify_bundle_source(str(path))
    except Exception:
        return {
            "verdict": "not_recognizable_or_not_hrevn",
            "verdict_label": "PAQUETE NO RECONOCIBLE / NO EMITIDO POR HREVN",
            "message": "El ZIP no contiene una estructura EB1 verificable por HREVN.",
            "emitted_by_hrevn": False,
            "files": {"ok": [], "altered": [], "missing": [], "unexpected": []},
            "roots": {"sealed": None, "recalculated": None, "registered": None},
            "signature": {"status": None, "valid": None, "valid_for_root": None},
            "anchor": {},
            "warnings": ["unrecognized_bundle_structure"],
            "errors": [],
        }

    checksums = verification.get("checksums") or {}
    sealed_root = signature_root or verification.get("root_hash_declared")
    recalculated_root = verification.get("root_hash_computed")
    bundle_id = manifest.get("workflow_id") if isinstance(manifest.get("workflow_id"), str) else None
    origin = _origin_check(bundle_id, sealed_root)
    signature_valid = verification.get("signature_valid")
    anchor = _anchor_summary(verification.get("anchor"), sealed_root)
    altered = checksums.get("failed") or []
    missing = checksums.get("missing") or []
    unexpected = checksums.get("unchecked") or []
    is_eb1 = bool(verification.get("schema_version") and sealed_root and recalculated_root)

    if not is_eb1:
        verdict = "not_recognizable_or_not_hrevn"
        label = "PAQUETE NO RECONOCIBLE / NO EMITIDO POR HREVN"
        message = "La estructura del ZIP no corresponde a un Evidence Bundle EB1 reconocible."
    elif signature_valid is True and sealed_root != recalculated_root:
        verdict = "modified_after_sealing"
        label = "BUNDLE MODIFICADO TRAS EL SELLADO"
        message = (
            f"La firma es válida para el root sellado ({sealed_root}), pero el contenido reproduce "
            f"un root distinto ({recalculated_root}). El paquete fue alterado después del sellado."
        )
    elif not origin["emitted_by_hrevn"] or signature_valid is not True:
        verdict = "not_recognizable_or_not_hrevn"
        label = "PAQUETE NO RECONOCIBLE / NO EMITIDO POR HREVN"
        message = "El paquete no consta como bundle emitido por HREVN o no está firmado con una clave reconocida."
    elif verification.get("valid") and anchor["status"] == "anchored" and anchor["root_matches_sealed"]:
        verdict = "verified"
        label = "VERIFIED"
        message = "Checksums internos OK, root EB1 reproducido, firma Ed25519 válida y anclaje Sepolia coincidente."
    else:
        verdict = "modified_after_sealing"
        label = "BUNDLE MODIFICADO TRAS EL SELLADO"
        message = "El paquete no supera todas las comprobaciones de integridad posteriores al sellado."

    return {
        "verdict": verdict,
        "verdict_label": label,
        "message": message,
        "bundle_id": bundle_id,
        "record_id": verification.get("aer_id"),
        "package_type": verification.get("package_type"),
        "schema_version": verification.get("schema_version"),
        "emitted_by_hrevn": origin["emitted_by_hrevn"],
        "origin": origin,
        "files": {
            "ok": checksums.get("passed") or [],
            "altered": altered,
            "missing": missing,
            "unexpected": unexpected,
        },
        "roots": {
            "sealed": sealed_root,
            "recalculated": recalculated_root,
            "registered": origin["registered_root_hash"],
        },
        "signature": {
            "status": verification.get("signature_status"),
            "valid": signature_valid,
            "algorithm": verification.get("signature_algorithm"),
            "public_key_id": verification.get("signature_public_key_id"),
            "valid_for_root": sealed_root if signature_valid is True else None,
        },
        "anchor": anchor,
        "warnings": verification.get("warnings") or [],
        "errors": verification.get("errors") or [],
    }


@router.post("/v1/public/evidence-bundle/audit-upload")
async def public_audit_bundle_upload(request: Request) -> dict[str, Any]:
    _enforce_audit_rate_limit(request)
    tmp_dir = Path(tempfile.mkdtemp(prefix="hrevn-eb1-audit-"))
    try:
        uploaded = await _store_limited_upload(request, tmp_dir)
        _validate_safe_zip(uploaded)
        return _audit_payload(uploaded)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/v1/bundles/{bundle_id}/download")
def download_bundle(bundle_id: str, _auth: AuthContext = Depends(resolve_auth_context)):
    path = resolve_bundle_download(bundle_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)
