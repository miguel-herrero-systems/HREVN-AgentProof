from __future__ import annotations

import argparse
from base64 import b64encode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ed25519 signing keys for HREVN EB1.")
    parser.add_argument("--public-key-id", default="hrevn-eb-ed25519-01")
    args = parser.parse_args()

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_key_b64 = b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode("ascii")
    public_key_b64 = b64encode(
        public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    print(f"HREVN_EB_SIGNING_ALGORITHM=Ed25519")
    print(f"HREVN_EB_SIGNING_PRIVATE_KEY={private_key_b64}")
    print(f"HREVN_EB_SIGNING_PUBLIC_KEY={public_key_b64}")
    print(f"HREVN_EB_SIGNING_PUBLIC_KEY_ID={args.public_key_id}")


if __name__ == "__main__":
    main()
