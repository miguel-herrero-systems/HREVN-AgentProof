from __future__ import annotations

from base64 import b64decode, b64encode
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from ..config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_signing_record(root_hash: str) -> dict[str, Any]:
    if not settings.hrevn_eb_signing_private_key or not settings.hrevn_eb_signing_public_key:
        return {
            "algorithm": settings.hrevn_eb_signing_algorithm,
            "public_key_id": settings.hrevn_eb_signing_public_key_id,
            "status": "signing_not_configured",
            "root_hash": root_hash,
        }

    try:
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            b64decode(settings.hrevn_eb_signing_private_key)
        )
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(b64decode(settings.hrevn_eb_signing_public_key))
        signature = private_key.sign(bytes.fromhex(root_hash))
        public_key_fingerprint = _sha256_text(
            b64encode(
                public_key.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode("ascii")
        )[:16]
    except Exception as exc:  # pragma: no cover - tested via status contract
        return {
            "algorithm": settings.hrevn_eb_signing_algorithm,
            "public_key_id": settings.hrevn_eb_signing_public_key_id,
            "status": "signing_failed",
            "root_hash": root_hash,
            "error": str(exc),
        }

    return {
        "algorithm": settings.hrevn_eb_signing_algorithm,
        "public_key_id": settings.hrevn_eb_signing_public_key_id,
        "public_key_b64": settings.hrevn_eb_signing_public_key,
        "public_key_fingerprint": public_key_fingerprint,
        "signature_b64": b64encode(signature).decode("ascii"),
        "signed_at": _utc_now(),
        "status": "signed",
        "root_hash": root_hash,
    }


def save_signing_artifact(*, artifact_dir: Path, record: dict[str, Any]) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "SIGNATURE_ED25519.json"
    path.write_text(_canonical_json(record) + "\n", encoding="utf-8")
    return path
