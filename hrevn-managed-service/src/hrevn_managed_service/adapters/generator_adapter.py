from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
import uuid
import zipfile
import hashlib

from ..config import settings
from ..services.blockchain_anchor_service import (
    anchor_eb1_root,
    build_blockchain_anchor_record,
    manifest_anchor_status,
)
from ..services.eb1_templates import build_eb1_human_files
from ..services.eb1_profile_registry import resolve_eb1_package_type
from ..services.signing_service import build_signing_record
from ..services.tooling_context_service import build_generation_tooling_context


SCHEMA_VERSION = "hrevn-aer-v0.3.3"
EB1_GROUP_DIRECTORIES = {
    "documents": "documents",
    "images": "images",
    "attachments": "attachments",
    "other_files": "other_files",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_today() -> str:
    return date.today().isoformat()


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_of_dict(value: dict[str, Any]) -> str:
    return _sha256_hex(_canonical_bytes(value))


@dataclass
class TraceRecord:
    test_id: str
    result: str
    confidence: str
    duration_ms: int
    tokens_used: int
    input_text: str | None = None
    raw_output: str | None = None
    validator_notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "test_id": self.test_id,
            "result": self.result,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
        }
        if self.input_text:
            data["input_text"] = self.input_text
        if self.raw_output:
            data["raw_output"] = self.raw_output
        if self.validator_notes:
            data["validator_notes"] = self.validator_notes
        if self.extra:
            data.update(self.extra)
        return data


@dataclass
class GeneratorConfig:
    agent_name: str
    model_version: str
    task_description: str
    test_environment: str
    issuer_id: str
    issuer_name: str
    issuer_type: str = "self_issued"
    evaluation_date: str | None = None
    output_prefix: str | None = None
    distribution_channel: str = "commercial-managed"
    delivery_mode: str = "api"
    license_id: str | None = None
    installation_id: str | None = None
    telemetry_enabled: bool = False


def _extract_integration_fields(record: dict[str, Any]) -> dict[str, Any]:
    integration: dict[str, Any] = {}

    if isinstance(record.get("integration_profile"), str) and record["integration_profile"].strip():
        integration["integration_profile"] = record["integration_profile"].strip()

    if isinstance(record.get("case_reference"), dict) and record["case_reference"]:
        integration["case_reference"] = record["case_reference"]

    deliverables = record.get("certified_deliverables")
    if isinstance(deliverables, list):
        filtered = [item for item in deliverables if isinstance(item, dict)]
        if filtered:
            integration["certified_deliverables"] = filtered

    return integration


def _strip_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalize_file_list(value: Any) -> list[Any] | None:
    if not isinstance(value, list):
        return None

    normalized: list[Any] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append({"name": text})
        elif isinstance(item, dict) and item:
            normalized.append(item)

    return normalized or None


def _extract_profiled_package_fields(record: dict[str, Any]) -> dict[str, Any]:
    profiled: dict[str, Any] = {}

    profile = _strip_text(record.get("profile"))
    if profile:
        profiled["profile"] = profile

    if isinstance(record.get("profile_inputs"), dict) and record["profile_inputs"]:
        profiled["profile_inputs"] = record["profile_inputs"]

    package_input: dict[str, Any] = {}
    for source_key, target_key in (
        ("package_title", "title"),
        ("package_summary", "summary"),
        ("issued_by", "issued_by"),
        ("input_notes", "notes"),
    ):
        value = _strip_text(record.get(source_key))
        if value:
            package_input[target_key] = value

    for source_key, target_key in (
        ("documents", "documents"),
        ("images", "images"),
        ("attachments", "attachments"),
        ("other_files", "other_files"),
    ):
        normalized = _normalize_file_list(record.get(source_key))
        if normalized:
            package_input[target_key] = normalized

    if package_input:
        profiled["package_input"] = package_input

    return profiled


def _normalize_eb1_file_item(group_name: str, index: int, item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        raw_filename = item
        raw_item: dict[str, Any] = {}
    elif isinstance(item, dict) and item:
        raw_filename = item.get("filename") or item.get("name") or ""
        raw_item = item
    else:
        raise ValueError(f"invalid_eb1_file_item:{group_name}:{index}")

    filename = Path(str(raw_filename).strip()).name
    if not filename:
        raise ValueError(f"missing_filename:{group_name}:{index}")

    relative_path = f"{EB1_GROUP_DIRECTORIES[group_name]}/{filename}"
    media_type = _strip_text(raw_item.get("media_type")) or _strip_text(raw_item.get("mime_type"))
    role = _strip_text(raw_item.get("role"))
    label = _strip_text(raw_item.get("label"))
    description = _strip_text(raw_item.get("description"))
    source_id = _strip_text(raw_item.get("document_id")) or _strip_text(raw_item.get("artifact_id"))

    normalized = {
        "source_group": group_name,
        "source_id": source_id or f"{group_name}-{index:03d}",
        "filename": filename,
        "relative_path": relative_path,
        "media_type": media_type,
        "role": role,
        "label": label,
        "description": description,
        "authoritative": bool(raw_item.get("authoritative", True)),
    }

    if "content" in raw_item:
        normalized["content"] = raw_item["content"]

    return normalized


def normalize_eb1_input_files(record: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for group_name in ("documents", "images", "attachments", "other_files"):
        items = record.get(group_name)
        if not isinstance(items, list):
            continue

        for index, item in enumerate(items, start=1):
            normalized.append(_normalize_eb1_file_item(group_name, index, item))

    return normalized


def _eb1_package_type(profile: str | None) -> str:
    return resolve_eb1_package_type(profile)


def build_eb1_bundle_metadata(record: dict[str, Any], issued_at: str) -> dict[str, Any]:
    return {
        "profile": _strip_text(record.get("profile")),
        "profile_inputs": record["profile_inputs"] if isinstance(record.get("profile_inputs"), dict) else {},
        "package_title": _strip_text(record.get("package_title")),
        "package_summary": _strip_text(record.get("package_summary")),
        "issued_by": _strip_text(record.get("issued_by")),
        "issued_at": _strip_text(record.get("issued_at")) or issued_at,
        "sample_only": bool(record.get("sample_only", False)),
        "language": _strip_text(record.get("language")) or "en",
        "input_notes": _strip_text(record.get("input_notes")),
    }


def build_eb1_manifest(
    record: dict[str, Any], normalized_files: list[dict[str, Any]], generated_at_utc: str
) -> dict[str, Any]:
    profile = _strip_text(record.get("profile"))
    title = _strip_text(record.get("package_title")) or "HREVN Evidence Bundle"
    language = _strip_text(record.get("language")) or "en"
    notes = _strip_text(record.get("input_notes"))

    artifacts: list[dict[str, Any]] = []
    authoritative_files: list[str] = []
    for index, item in enumerate(normalized_files, start=1):
        artifact = {
            "artifact_id": item.get("source_id") or f"art-{index:03d}",
            "role": item.get("role"),
            "filename": item["filename"],
            "relative_path": item["relative_path"],
            "media_type": item.get("media_type"),
            "authoritative": bool(item.get("authoritative", True)),
        }
        if item.get("label"):
            artifact["label"] = item["label"]
        if item.get("description"):
            artifact["description"] = item["description"]
        artifacts.append(artifact)
        if artifact["authoritative"]:
            authoritative_files.append(artifact["relative_path"])

    manifest = {
        "bundle_profile": "evidence_bundle_eb1_v1",
        "package_family": "hrevn_evidence_bundle",
        "package_type": _eb1_package_type(profile),
        "title": title,
        "language": language,
        "generated_at_utc": generated_at_utc,
        "artifact_count": len(artifacts),
        "authoritative_files": authoritative_files,
        "root_hash_algorithm": "HREVN_ROOT_EB1_V1",
        "root_hash_scope": "manifest.authoritative_files",
        "root_hash_spec_file": "ROOT_SPEC_EB1.txt",
        "artifacts": artifacts,
        "notes": [notes] if notes else [],
    }
    return manifest


def build_eb1_root_spec_text() -> str:
    return (
        "HREVN_ROOT_EB1_V1\n"
        "scope=manifest.authoritative_files\n"
        "path_basis=relative_to_bundle_root_without_outer_zip_prefix\n"
        "line_format=relative_path:sha256hex\n"
        "sort=ascending_ascii_by_relative_path\n"
        "separator=LF\n"
        "trailing_newline=false\n"
        "encoding=utf-8\n"
    )


def build_eb1_root_hash(file_bytes_by_relative_path: dict[str, bytes], authoritative_files: list[str]) -> str:
    missing = [path for path in authoritative_files if path not in file_bytes_by_relative_path]
    if missing:
        raise ValueError(f"missing_authoritative_files:{','.join(missing)}")

    lines = [
        f"{relative_path}:{_sha256_hex(file_bytes_by_relative_path[relative_path])}"
        for relative_path in sorted(authoritative_files)
    ]
    serialized = "\n".join(lines)
    return _sha256_hex(serialized.encode("utf-8"))


def build_eb1_checksums(bundle_files: dict[str, bytes]) -> str:
    lines: list[str] = []
    for relative_path in sorted(name for name in bundle_files if name != "CHECKSUMS.sha256"):
        lines.append(f"{_sha256_hex(bundle_files[relative_path])}  {relative_path}")
    return "\n".join(lines) + "\n"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8")


def _eb1_file_content_bytes(item: dict[str, Any]) -> bytes:
    content = item.get("content")
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    raise ValueError(f"missing_content:{item['relative_path']}")


def _build_payload(
    record: dict[str, Any], traces: list[TraceRecord], config: GeneratorConfig, record_id: str, issued_at: str
) -> dict[str, Any]:
    passed = sum(1 for t in traces if t.result == "PASS")
    failed = sum(1 for t in traces if t.result == "FAIL")
    review = sum(1 for t in traces if t.result == "HUMAN_REVIEW_REQUIRED")
    total = len(traces)
    automatable = total - review
    score = round((passed / automatable) * 100, 1) if automatable else 0.0
    overall = "PASS" if failed == 0 else "FAIL"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id,
        "issued_at": issued_at,
        "issuer": {
            "id": config.issuer_id,
            "name": config.issuer_name,
            "type": config.issuer_type,
        },
        "agent_name": config.agent_name,
        "model_version": config.model_version,
        "task_description": config.task_description,
        "test_environment": config.test_environment,
        "evaluation_date": config.evaluation_date or _utc_today(),
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "human_review": review,
            "score_pct": score,
            "score_basis": f"{passed}/{automatable} automatable tests",
            "overall_result": overall,
        },
        "test_traces": [trace.to_dict() for trace in traces],
        "signature_status": "unsigned",
        "scope_and_limitations": [
            "This record documents the evaluation of a specific agent version under controlled conditions.",
            "It does not certify general accuracy, legal validity, or fitness for production deployment.",
            "Results apply only to the tested inputs and may not generalise.",
            "Cases marked HUMAN_REVIEW_REQUIRED require manual validation before any deployment decision.",
        ],
    }
    payload.update(_extract_integration_fields(record))
    payload.update(_extract_profiled_package_fields(record))

    hashable = {k: v for k, v in payload.items() if k not in ("payload_hash", "manifest_hash")}
    payload["payload_hash"] = _sha256_of_dict(hashable)
    payload["manifest_hash"] = _sha256_of_dict(
        {"files": sorted(["payload.json", "issuance.json", "manifest.json", "CHECKSUMS.sha256", "ROOT_HASH_SHA256.txt"])}
    )
    return payload


def _build_issuance(payload: dict[str, Any], config: GeneratorConfig, issued_at: str) -> dict[str, Any]:
    issuance = {
        "issuer": payload["issuer"]["name"],
        "issuer_id": payload["issuer"]["id"],
        "issuer_type": payload["issuer"]["type"],
        "signature_status": "unsigned",
        "signed_payload_hash": payload["payload_hash"],
        "issued_at": issued_at,
        "tooling_context": build_generation_tooling_context(
            distribution_channel=config.distribution_channel,
            delivery_mode=config.delivery_mode,
            license_id=config.license_id,
            installation_id=config.installation_id,
            telemetry_enabled=config.telemetry_enabled,
            generated_at=issued_at,
        ),
    }
    return issuance


def _build_checksums(files: dict[str, bytes]) -> str:
    lines = []
    for name in sorted(files.keys()):
        lines.append(f"{_sha256_hex(files[name])}  {name}")
    return "\n".join(lines) + "\n"


def _build_root_hash(checksums_text: str, authoritative_files: list[str]) -> str:
    lines = {
        parts[1].strip(): parts[0].strip()
        for line in checksums_text.splitlines()
        if (parts := line.strip().split(None, 1)) and len(parts) == 2
    }
    pairs = [f"{name}:{lines[name]}" for name in sorted(authoritative_files) if name in lines]
    serialized = "\n".join(pairs)
    return _sha256_hex(serialized.encode("utf-8"))


def _build_manifest(record_id: str, bundle_id: str, issued_at: str, artifact_names: list[str]) -> dict[str, Any]:
    root_scope = ["payload.json", "issuance.json", "manifest.json"]
    return {
        "aer_id": record_id,
        "record_id": record_id,
        "workflow_id": bundle_id,
        "bundle_profile": "managed_generated_aer_v1",
        "package_type": "managed_generated_aer_v1",
        "package_family": "hrevn_aer",
        "version": SCHEMA_VERSION,
        "generated_at_utc": issued_at,
        "artifact_count": len(artifact_names),
        "artifacts": [{"artifact": name} for name in artifact_names],
        "root_scope": root_scope,
        "checksum_scope": [name for name in artifact_names if name != "CHECKSUMS.sha256"],
        "authoritative_files": root_scope + ["ROOT_HASH_SHA256.txt"],
        "supporting_files": [],
        "verification_model": "ROOT_AER_V1",
        "root_serialization": {
            "encoding": "utf-8",
            "format": "filename:sha256",
            "line_separator": "\\n",
            "sort_order": "ascending filename",
            "trailing_newline": False,
        },
        "signature_status": "unsigned",
        "external_anchor_status": "not_anchored",
    }


def generate_verified_record_bundle(
    record: dict[str, Any], traces: list[dict[str, Any]], bundle_id: str, output_dir: Path
) -> dict[str, Any]:
    issued_at = _utc_now()
    record_id = f"AER-{bundle_id[-8:]}"
    config = GeneratorConfig(
        agent_name=record["agent_name"],
        model_version=record["model_version"],
        task_description=record["task_description"],
        test_environment=record["test_environment"],
        issuer_id=record["issuer_id"],
        issuer_name=record["issuer_name"],
        issuer_type=record.get("issuer_type", "self_issued"),
        distribution_channel=record.get("distribution_channel", "commercial-managed"),
        delivery_mode=record.get("delivery_mode", "api"),
        license_id=record.get("license_id") or settings.managed_license_id,
        installation_id=record.get("installation_id") or settings.managed_installation_id,
        telemetry_enabled=bool(record.get("telemetry_enabled", False)),
    )
    trace_records = [TraceRecord(**trace) for trace in traces]
    payload = _build_payload(record, trace_records, config, record_id, issued_at)
    issuance = _build_issuance(payload, config, issued_at)
    initial_artifacts = [
        "payload.json",
        "issuance.json",
        "manifest.json",
        "CHECKSUMS.sha256",
        "ROOT_HASH_SHA256.txt",
    ]
    manifest = _build_manifest(record_id=record_id, bundle_id=bundle_id, issued_at=issued_at, artifact_names=initial_artifacts)
    files: dict[str, bytes] = {
        "payload.json": json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        "issuance.json": json.dumps(issuance, indent=2, ensure_ascii=False).encode("utf-8"),
        "manifest.json": json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
    }
    root_hash = _build_root_hash(
        _build_checksums(files),
        manifest["root_scope"],
    )
    files["ROOT_HASH_SHA256.txt"] = root_hash.encode("utf-8")
    checksums_scope_files = {name: files[name] for name in files}
    checksums_text = _build_checksums(checksums_scope_files)
    files["CHECKSUMS.sha256"] = checksums_text.encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"{bundle_id}.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in sorted(files.items()):
            zf.writestr(name, content)

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=settings.bundle_retention_hours)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")

    return {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_path),
        "record_id": record_id,
        "schema_version": SCHEMA_VERSION,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def generate_evidence_bundle_eb1(
    record: dict[str, Any], traces: list[dict[str, Any]], bundle_id: str, output_dir: Path
) -> dict[str, Any]:
    issued_at = _utc_now()
    bundle_record_id = f"EB1-{bundle_id[-8:]}"

    normalized_files = normalize_eb1_input_files(record)
    bundle_metadata = build_eb1_bundle_metadata(record, issued_at=issued_at)
    manifest = build_eb1_manifest(record, normalized_files, generated_at_utc=issued_at)

    bundle_files: dict[str, bytes] = {}
    for item in normalized_files:
        bundle_files[item["relative_path"]] = _eb1_file_content_bytes(item)

    root_hash = build_eb1_root_hash(bundle_files, manifest["authoritative_files"])
    signing_record = build_signing_record(root_hash)
    anchor_network = _strip_text(record.get("anchor_network")) or settings.hrevn_eb_anchor_network or "base"
    anchor_method = _strip_text(record.get("anchor_method")) or settings.hrevn_eb_anchor_method or "hrevn_managed_anchor"
    manual_transaction_reference = _strip_text(record.get("anchor_transaction_reference"))
    manual_status = record.get("anchor_status")
    manual_error = _strip_text(record.get("anchor_error"))
    manual_anchored_at = _strip_text(record.get("anchor_anchored_at"))
    if manual_transaction_reference or manual_status or manual_error or manual_anchored_at:
        anchor_record = build_blockchain_anchor_record(
            root_hash,
            network=anchor_network,
            anchor_method=anchor_method,
            transaction_reference=manual_transaction_reference,
            anchored_at=manual_anchored_at,
            status=manual_status,
            error=manual_error,
        )
    elif settings.hrevn_eb_anchor_emit_real:
        anchor_record = anchor_eb1_root(root_hash, network=anchor_network)
    else:
        anchor_record = build_blockchain_anchor_record(
            root_hash,
            network=anchor_network,
            anchor_method=anchor_method,
        )
    anchor_status = manifest_anchor_status(anchor_record)
    manifest["external_anchor_status"] = anchor_status
    manifest["signature_status"] = signing_record.get("status") or "unsigned"
    manifest["signature_algorithm"] = signing_record.get("algorithm")
    manifest["signature_public_key_id"] = signing_record.get("public_key_id")
    manifest["signature_artifact"] = "SIGNATURE_ED25519.json"
    manifest["record_id"] = bundle_record_id
    manifest["workflow_id"] = bundle_id

    bundle_files["bundle-metadata.json"] = _json_bytes(bundle_metadata)
    bundle_files["manifest.json"] = _json_bytes(manifest)
    bundle_files["ROOT_HASH_SHA256.txt"] = root_hash.encode("utf-8")
    bundle_files["ROOT_SPEC_EB1.txt"] = build_eb1_root_spec_text().encode("utf-8")
    bundle_files["SIGNATURE_ED25519.json"] = _json_bytes(signing_record)
    bundle_files["BLOCKCHAIN_ANCHOR.json"] = _json_bytes(anchor_record)

    human_files = build_eb1_human_files(
        bundle_metadata,
        manifest,
        anchor_status=anchor_status,
        anchor_network=anchor_record.get("network"),
        anchor_transaction_reference=anchor_record.get("transaction_reference"),
        anchor_explorer_url=anchor_record.get("explorer_url"),
        signature_status=manifest["signature_status"],
        signature_algorithm=manifest.get("signature_algorithm"),
        signature_public_key_id=manifest.get("signature_public_key_id"),
    )
    for name, text in human_files.items():
        bundle_files[name] = text.encode("utf-8")

    checksums_text = build_eb1_checksums(bundle_files)
    bundle_files["CHECKSUMS.sha256"] = checksums_text.encode("utf-8")

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"{bundle_id}.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in sorted(bundle_files.items()):
            zf.writestr(name, content)

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=settings.bundle_retention_hours)).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")

    return {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_path),
        "record_id": bundle_record_id,
        "schema_version": "hrevn-eb1-v1",
        "issued_at": issued_at,
        "expires_at": expires_at,
        "bundle_profile": manifest["bundle_profile"],
        "package_type": manifest["package_type"],
        "root_hash": root_hash,
        "anchor_status": anchor_status,
        "anchor": anchor_record,
        "signature_status": manifest["signature_status"],
        "signature_algorithm": manifest.get("signature_algorithm"),
        "signature_public_key_id": manifest.get("signature_public_key_id"),
    }


def generate_bundle(record: dict[str, Any], traces: list[dict[str, Any]], bundle_id: str, output_dir: Path) -> dict[str, Any]:
    return generate_verified_record_bundle(record=record, traces=traces, bundle_id=bundle_id, output_dir=output_dir)


def new_bundle_id() -> str:
    return f"BND-{uuid.uuid4().hex[:12].upper()}"
