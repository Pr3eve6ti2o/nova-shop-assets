#!/usr/bin/env python3
"""make_wallet.py — generate the Nova Shop Bot HD wallet via Trust Wallet wallet-core.

1. Runs tools/hdwallet-gen/generate.js (Node + @trustwallet/wallet-core WASM):
   validates official test vectors, then generates a fresh 24-word wallet and
   exports BTC zpub / ETH xpub / TRX xpub / TON address.
2. Cross-verifies with the bot's OWN derivation code (crypto_payments.derive_address):
   the addresses the bot will hand to customers must match wallet-core's.
3. Encrypts the mnemonic with AES-256-GCM under a fresh random 32-byte data key.
   Ciphertext -> secrets/seed.enc.json (0600). The data key is printed ONCE and
   never stored on disk.
4. Writes XPUB_BTC / XPUB_ETH / XPUB_TRX / TON_DEPOSIT_ADDRESS into .env.
5. Copies the encrypted bundle to ~/workspace/your_files/nova-shop-seed-backup/
   so the owner can download it any time.

The mnemonic exists in plaintext only in this process's memory and in the
operator's hands. Run once.
"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402


def main() -> None:
    node = shutil.which("node") or "/usr/bin/node"
    gen = os.path.join(BASE, "tools", "hdwallet-gen", "generate.js")
    print("Generating wallet with Trust Wallet wallet-core ...", flush=True)
    proc = subprocess.run([node, gen], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit("wallet-core generation failed")
    data = json.loads(proc.stdout)

    failed = [c["name"] for c in data["checks"] if not c["ok"]]
    if failed:
        raise SystemExit(f"wallet-core self-checks failed: {failed}")
    print(f"wallet-core checks passed ({len(data['checks'])}/{len(data['checks'])})")

    # ---- cross-verify with the bot's own derivation code ----
    from crypto_payments import derive_address  # noqa: E402
    assert derive_address("btc", data["btc_zpub"], 1) == data["samples"]["btc1"], "BTC mismatch"
    assert derive_address("eth", data["eth_xpub"], 1) == data["samples"]["eth1"], "ETH mismatch"
    assert derive_address("trx", data["trx_xpub"], 1) == data["samples"]["trx1"], "TRX mismatch"
    print("bot derivation cross-check passed: Python hdwallet == wallet-core WASM")

    # ---- encrypt the seed ----
    data_key = secrets.token_bytes(32)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(data_key).encrypt(nonce, data["mnemonic"].encode(), b"nova-shop-seed-v1")
    enc = {
        "alg": "AES-256-GCM",
        "kdf": "none - random 256-bit data key (shown once at creation)",
        "nonce_b64": base64.b64encode(nonce).decode(),
        "ciphertext_b64": base64.b64encode(ct).decode(),
        "created": "nova-shop tools/make_wallet.py",
        "note": "Decrypt with tools/decrypt_seed.py and the data key.",
    }
    secrets_dir = os.path.join(BASE, "secrets")
    os.makedirs(secrets_dir, exist_ok=True)
    enc_path = os.path.join(secrets_dir, "seed.enc.json")
    with open(enc_path, "w") as f:
        json.dump(enc, f, indent=2)
    os.chmod(enc_path, 0o600)
    print(f"encrypted seed written to {enc_path} (0600)")

    # ---- .env ----
    env_path = os.path.join(BASE, ".env")
    with open(env_path) as f:
        env_txt = f.read()
    additions = {
        "XPUB_BTC": data["btc_zpub"],
        "XPUB_ETH": data["eth_xpub"],
        "XPUB_TRX": data["trx_xpub"],
        "TON_DEPOSIT_ADDRESS": data["ton_address"],
    }
    with open(env_path, "a") as f:
        for k, v in additions.items():
            if f"{k}=" not in env_txt:
                f.write(f"\n{k}={v}\n")
    os.chmod(env_path, 0o600)
    print(".env updated with xpubs + TON address")

    # ---- download bundle ----
    bundle = os.path.expanduser("~/workspace/your_files/nova-shop-seed-backup")
    os.makedirs(bundle, exist_ok=True)
    shutil.copy(enc_path, os.path.join(bundle, "seed.enc.json"))
    shutil.copy(os.path.join(BASE, "tools", "decrypt_seed.py"), os.path.join(bundle, "decrypt_seed.py"))
    shutil.copy(os.path.join(BASE, "secrets", "WALLET_README.md"), os.path.join(bundle, "README.txt"))
    print(f"download bundle ready at {bundle}")

    # ---- one-time operator output ----
    print("\n" + "=" * 64)
    print("PUBLIC (safe to keep):")
    print(f"  BTC zpub : {data['btc_zpub'][:20]}...  (m/84'/0'/0')")
    print(f"  ETH xpub : {data['eth_xpub'][:20]}...  (m/44'/60'/0')")
    print(f"  TRX xpub : {data['trx_xpub'][:20]}...  (m/44'/195'/0')")
    print(f"  TON      : {data['ton_address']}  ({data['ton_path']})")
    print(f"  wallet-core@{data['wallet_core_version']}")
    print("=" * 64)
    print("DATA KEY (hex) — save in a password manager, never stored on disk:")
    print("  " + data_key.hex())
    print("=" * 64)
    print("SEED PHRASE (24 words) — write down OFFLINE, never share:")
    print("  " + data["mnemonic"])
    print("=" * 64)


if __name__ == "__main__":
    main()
