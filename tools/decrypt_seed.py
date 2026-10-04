#!/usr/bin/env python3
"""decrypt_seed.py — recover the Nova Shop seed phrase from the encrypted backup.

Usage:
    python3 decrypt_seed.py seed.enc.json <64-hex-char-data-key>

Needs: pip install cryptography
"""
import base64
import json
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    with open(sys.argv[1]) as f:
        enc = json.load(f)
    key = bytes.fromhex(sys.argv[2])
    if len(key) != 32:
        raise SystemExit("data key must be 32 bytes (64 hex chars)")
    pt = AESGCM(key).decrypt(
        base64.b64decode(enc["nonce_b64"]),
        base64.b64decode(enc["ciphertext_b64"]),
        b"nova-shop-seed-v1",
    )
    print(pt.decode())


if __name__ == "__main__":
    main()
