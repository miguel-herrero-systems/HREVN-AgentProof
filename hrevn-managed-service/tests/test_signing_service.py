from __future__ import annotations

import base64
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from hrevn_managed_service.config import settings
from hrevn_managed_service.services.signing_service import build_signing_record, save_signing_artifact


def _set_setting(name: str, value):
    original = getattr(settings, name)
    object.__setattr__(settings, name, value)
    return original


def test_build_signing_record_returns_not_configured_without_keys():
    original_private = _set_setting("hrevn_eb_signing_private_key", "")
    original_public = _set_setting("hrevn_eb_signing_public_key", "")
    original_key_id = _set_setting("hrevn_eb_signing_public_key_id", "hrevn-eb-ed25519-01")
    try:
        record = build_signing_record("ab" * 32)
    finally:
        object.__setattr__(settings, "hrevn_eb_signing_private_key", original_private)
        object.__setattr__(settings, "hrevn_eb_signing_public_key", original_public)
        object.__setattr__(settings, "hrevn_eb_signing_public_key_id", original_key_id)

    assert record["status"] == "signing_not_configured"
    assert record["root_hash"] == "ab" * 32


def test_build_signing_record_signs_root_hash_with_ed25519():
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_key_b64 = base64.b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_key_b64 = base64.b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    original_private = _set_setting("hrevn_eb_signing_private_key", private_key_b64)
    original_public = _set_setting("hrevn_eb_signing_public_key", public_key_b64)
    original_key_id = _set_setting("hrevn_eb_signing_public_key_id", "hrevn-eb-ed25519-test")
    try:
        record = build_signing_record("cd" * 32)
    finally:
        object.__setattr__(settings, "hrevn_eb_signing_private_key", original_private)
        object.__setattr__(settings, "hrevn_eb_signing_public_key", original_public)
        object.__setattr__(settings, "hrevn_eb_signing_public_key_id", original_key_id)

    assert record["status"] == "signed"
    assert record["algorithm"] == "Ed25519"
    assert record["public_key_id"] == "hrevn-eb-ed25519-test"
    assert record["root_hash"] == "cd" * 32
    assert record["signature_b64"]
    public_key.verify(base64.b64decode(record["signature_b64"]), bytes.fromhex("cd" * 32))


def test_save_signing_artifact_writes_expected_filename(tmp_path):
    path = save_signing_artifact(
        artifact_dir=tmp_path,
        record={"status": "signed", "root_hash": "ef" * 32, "algorithm": "Ed25519"},
    )

    assert path.name == "SIGNATURE_ED25519.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "signed"
    assert data["root_hash"] == "ef" * 32
