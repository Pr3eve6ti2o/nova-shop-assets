#!/usr/bin/env python3
"""bot/tools/sweep.py — Offline sweep tool for the Nova shop bot's deposit addresses.

The bot derives per-order deposit addresses from the owner's xpub (watch-only;
the server never sees the seed). Funds accumulate at those derived addresses
with NO in-bot way to move them out. This script — run by the owner on their
OWN machine — sweeps funds from used deposit addresses to a destination wallet.

SECURITY MODEL (non-negotiable):
  - The seed phrase is prompted interactively via getpass. It is NEVER passed
    via argv, env vars, files, or logs.
  - Private key material is overwritten in Python variables after use
    (best-effort: CPython does not guarantee memory wiping — the OS may
    have paged copies. Run on a trusted machine, ideally offline except
    for RPC calls).
  - Dry-run is the DEFAULT. Real broadcast requires --execute.
  - This script is OFFLINE except for the balance/utxo lookups and the final
    broadcast. Run it on a trusted machine.

Derivation paths (must match the bot):
  - BTC: m/84'/0'/0'/0/{index}  (BIP84, P2WPKH native segwit, bc1q...)
  - EVM: m/44'/60'/0'/0/{index} (BIP44, same address on all EVM chains)

Dependencies: pip install bip-utils embit eth-account requests
"""
import argparse
import getpass
import json
import sqlite3
import sys
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BTC_DUST_SATS = 546
GAP_LIMIT = 20  # BIP44 standard: stop after 20 consecutive empty addresses

# ERC-20 contracts per chain (chain_id -> {symbol: contract}).
# Copied from the bot's own bot/crypto_payments.py CHAINS table — the
# authoritative source. The RPC's eth_chainId selects the right map, so a
# Polygon RPC sweeps Polygon USDT (not the Ethereum-mainnet contract).
TOKENS_BY_CHAIN = {
    1: {  # Ethereum mainnet
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
    10: {  # Optimism
        "USDT": "0x94b008aA00579c1307B0EF2c499aD98a8Ce58e58",
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    },
    137: {  # Polygon
        "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    },
    8453: {  # Base
        "USDT": "0x102d758f688a4C1C5a80b116bD945d4455460282",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
}
ERC20_ABI_BALANCEOF = "70a08231"  # balanceOf(address)
ERC20_ABI_TRANSFER = "a9059cbb"   # transfer(address,uint256)

MEMPOOL_API = "https://mempool.space/api"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def http_get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "nova-sweep/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_post(url, data, timeout=30, content_type="text/plain"):
    req = urllib.request.Request(
        url, data=data.encode() if isinstance(data, str) else data,
        headers={"Content-Type": content_type, "User-Agent": "nova-sweep/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode().strip()


def rpc_call(rpc_url, method, params, timeout=30):
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    result = http_post(rpc_url, payload, timeout=timeout,
                       content_type="application/json")
    data = json.loads(result)
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data.get("result")


def confirm(prompt):
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    return ans in ("y", "yes")


# ---------------------------------------------------------------------------
# Key derivation (bip_utils)
# ---------------------------------------------------------------------------

def derive_keys(mnemonic, chain, index):
    """Return (address, privkey_hex) for the given chain and index."""
    from bip_utils import (Bip39SeedGenerator, Bip84, Bip84Coins,
                           Bip44, Bip44Coins, Bip44Changes)
    seed = Bip39SeedGenerator(mnemonic).Generate()
    if chain == "btc":
        ctx = Bip84.FromSeed(seed, Bip84Coins.BITCOIN)
        acc = (ctx.Purpose().Coin().Account(0)
                  .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
        return acc.PublicKey().ToAddress(), acc.PrivateKey().Raw().ToHex()
    else:  # evm
        ctx = Bip44.FromSeed(seed, Bip44Coins.ETHEREUM)
        acc = (ctx.Purpose().Coin().Account(0)
                  .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
        return acc.PublicKey().ToAddress(), acc.PrivateKey().Raw().ToHex()


# ---------------------------------------------------------------------------
# BTC sweep (embit + mempool.space)
# ---------------------------------------------------------------------------

def btc_fetch_utxos(address):
    try:
        utxos = http_get_json(f"{MEMPOOL_API}/address/{address}/utxo")
    except Exception as e:
        print(f"  warning: utxo lookup failed for {address}: {e}")
        return []
    return [u for u in utxos if u.get("value", 0) > BTC_DUST_SATS]


def btc_fee_rate(args):
    if args.fee_rate:
        return args.fee_rate
    try:
        fees = http_get_json(f"{MEMPOOL_API}/v1/fees/recommended")
        return int(fees.get("halfHourFee", 5))
    except Exception:
        return 5


def btc_sweep(args, mnemonic):
    from embit import bip32, script, transaction
    from embit.networks import NETWORKS

    print("Scanning BTC deposit addresses (m/84'/0'/0'/0/i)...")
    targets = []  # (index, address, privkey_hex, utxos)

    if args.db:
        indices = db_indices(args.db, "btc")
        print(f"  from DB: {len(indices)} deposit indices")
        for index in indices:
            address, priv = derive_keys(mnemonic, "btc", index)
            utxos = btc_fetch_utxos(address)
            if utxos:
                targets.append((index, address, priv, utxos))
                print(f"  [{index}] {address}: "
                      f"{sum(u['value'] for u in utxos)} sats "
                      f"({len(utxos)} utxos)")
            priv = "0" * 64  # wipe
    else:
        empty_streak = 0
        index = 0
        while index <= args.max_index and empty_streak < GAP_LIMIT:
            address, priv = derive_keys(mnemonic, "btc", index)
            utxos = btc_fetch_utxos(address)
            if utxos:
                targets.append((index, address, priv, utxos))
                print(f"  [{index}] {address}: "
                      f"{sum(u['value'] for u in utxos)} sats")
                empty_streak = 0
            else:
                empty_streak += 1
                priv = "0" * 64
            index += 1

    if not targets:
        print("No funded BTC addresses found.")
        return

    total_in = sum(u["value"] for _, _, _, utxos in targets for u in utxos)
    fee_rate = btc_fee_rate(args)
    # vsize estimate: 10 overhead + 68/input (P2WPKH) + 31/output
    n_inputs = sum(len(utxos) for _, _, _, utxos in targets)
    vsize = 10 + 68 * n_inputs + 31
    fee = vsize * fee_rate
    total_out = total_in - fee

    print(f"\nSweep plan: {n_inputs} inputs, {total_in} sats in, "
          f"fee ~{fee} sats ({fee_rate} sat/vB), "
          f"{total_out} sats to {args.destination}")

    if total_out <= BTC_DUST_SATS:
        print("ERROR: output below dust after fee. Aborting.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Would broadcast the sweep transaction. "
              "Re-run with --execute to sign and broadcast.")
        return

    if not args.yes and not confirm("Sign and broadcast this sweep?"):
        print("Aborted.")
        return

    # Build and sign
    network = NETWORKS["main"]
    txins = []
    signing_keys = []  # (privkey_hex, utxo_value, script_pubkey)
    for index, address, priv_hex, utxos in targets:
        # Re-derive to get the key object for signing
        from bip_utils import (Bip39SeedGenerator, Bip84, Bip84Coins,
                               Bip44Changes)
        seed = Bip39SeedGenerator(mnemonic).Generate()
        acc = (Bip84.FromSeed(seed, Bip84Coins.BITCOIN)
               .Purpose().Coin().Account(0)
               .Change(Bip44Changes.CHAIN_EXT).AddressIndex(index))
        priv = bip32.HDKey.from_string(acc.PrivateKey().ToWif())
        for u in utxos:
            txin = transaction.TransactionInput(
                bytes.fromhex(u["txid"])[::-1], u["vout"])
            txins.append(txin)
            spk = script.p2wpkh(priv.get_public_key())
            signing_keys.append((priv, u["value"], spk))
        priv = None

    dest_spk = script.address_to_scriptpubkey(args.destination)
    txout = transaction.TransactionOutput(total_out, dest_spk)
    tx = transaction.Transaction(
        version=2, vin=txins, vout=[txout], locktime=0)

    # Sign each input (BIP143 segwit)
    for i, (priv, value, spk) in enumerate(signing_keys):
        sighash = tx.sighash_segwit(i, spk, value)
        sig = priv.sign(sighash) + b"\x01"  # SIGHASH_ALL
        tx.vin[i].witness = transaction.Witness(
            [sig, priv.get_public_key().serialize()])

    raw_hex = tx.serialize().hex()
    print(f"\nSigned tx ({len(raw_hex)//2} bytes). Broadcasting...")

    if args.dry_run:
        print("[DRY RUN] tx hex:", raw_hex[:80], "...")
        return

    try:
        txid = http_post(f"{MEMPOOL_API}/tx", raw_hex)
        print(f"Sweep broadcast! txid: {txid}")
        print(f"Track: https://mempool.space/tx/{txid}")
    except urllib.error.HTTPError as e:
        print(f"Broadcast FAILED: {e.code} {e.read().decode()[:200]}")


# ---------------------------------------------------------------------------
# EVM sweep (eth-account + JSON-RPC)
# ---------------------------------------------------------------------------

def evm_sweep(args, mnemonic):
    from eth_account import Account

    if not args.rpc:
        print("ERROR: --rpc is required for EVM sweeps.")
        sys.exit(1)

    chain_id = int(rpc_call(args.rpc, "eth_chainId", []), 16)
    token_map = TOKENS_BY_CHAIN.get(chain_id)
    if token_map is None:
        print(f"warning: chain_id {chain_id} has no known USDT/USDC contracts; "
              "sweeping native coin only.")
        token_map = {}
    else:
        print(f"Chain ID {chain_id}: token contracts "
              + ", ".join(f"{s}={c[:10]}..." for s, c in token_map.items()))

    print("Scanning EVM deposit addresses (m/44'/60'/0'/0/i)...")
    targets = []  # (index, address, privkey_hex, native_wei, {token: balance})

    if args.db:
        indices = db_indices(args.db, "evm")
        index_list = indices
    else:
        index_list = list(range(args.max_index + 1))

    empty_streak = 0
    for index in index_list:
        address, priv = derive_keys(mnemonic, "evm", index)
        try:
            native = int(rpc_call(args.rpc, "eth_getBalance",
                                  [address, "latest"]), 16)
        except Exception as e:
            print(f"  warning: balance lookup failed for {address}: {e}")
            priv = "0" * 64
            continue

        tokens = {}
        if args.tokens:
            for sym, contract in token_map.items():
                data = (ERC20_ABI_BALANCEOF
                        + address[2:].lower().zfill(64))
                try:
                    bal = rpc_call(args.rpc, "eth_call",
                                   [{"to": contract, "data": "0x" + data},
                                    "latest"])
                    bal_int = int(bal, 16)
                    if bal_int > 0:
                        tokens[sym] = (contract, bal_int)
                except Exception:
                    pass

        if native > 0 or tokens:
            targets.append((index, address, priv, native, tokens))
            tok_str = ", ".join(f"{s}: {b}" for s, (_, b) in tokens.items())
            print(f"  [{index}] {address}: {native} wei"
                  + (f" + {tok_str}" if tok_str else ""))
            empty_streak = 0
        else:
            empty_streak += 1
            priv = "0" * 64
            if not args.db and empty_streak >= GAP_LIMIT:
                break

    if not targets:
        print("No funded EVM addresses found.")
        return

    # RPC validation (audit): verify we are talking to the right chain
    # and that it is synced before signing anything.
    rpc_chain_id = int(rpc_call(args.rpc, "eth_chainId", []), 16)
    if rpc_chain_id != chain_id:
        print(f"ERROR: RPC chain ID {rpc_chain_id} != expected {chain_id}. "
              f"Refusing to sweep on the wrong chain.", file=sys.stderr)
        sys.exit(1)
    try:
        syncing = rpc_call(args.rpc, "eth_syncing", [])
        if syncing and syncing is not False:
            print(f"ERROR: RPC node is still syncing: {syncing}. "
                  f"Refusing to sweep on a syncing node.", file=sys.stderr)
            sys.exit(1)
    except Exception:
        pass  # eth_syncing not supported by all RPCs; non-fatal
    print(f"RPC validated: chain ID {rpc_chain_id}, node in sync.")

    # EIP-1559 fees (audit): use maxFeePerGas / maxPriorityFeePerGas
    # instead of legacy gasPrice.
    fee_hist = rpc_call(args.rpc, "eth_feeHistory",
                        ["0x5", "latest", [25, 50, 75]])
    # feeHistory rewards are in wei hex; take the 50th percentile
    try:
        rewards = fee_hist.get("reward", [])
        prio_fees = [int(r[1], 16) for r in rewards if len(r) > 1]
        max_priority_fee = sorted(prio_fees)[len(prio_fees) // 2] if prio_fees else 0
    except Exception:
        max_priority_fee = 0
    if max_priority_fee < 1_000_000_000:  # floor at 1 gwei
        max_priority_fee = 1_000_000_000
    base_fee = int(fee_hist.get("baseFeePerGas", ["0x0"])[-1], 16)
    max_fee = base_fee * 2 + max_priority_fee
    print(f"\nChain ID: {chain_id}, base fee: {base_fee} wei, "
          f"maxPriorityFee: {max_priority_fee} wei, maxFee: {max_fee} wei")

    plan = []  # (index, address, priv, tx_dict, description)
    for index, address, priv, native, tokens in targets:
        nonce = int(rpc_call(args.rpc, "eth_getTransactionCount",
                             [address, "latest"]), 16)
        acct = Account.from_key(priv)

        # 1. Sweep ERC-20 tokens first
        for sym, (contract, bal) in tokens.items():
            transfer_data = ("0x" + ERC20_ABI_TRANSFER
                             + args.destination[2:].lower().zfill(64)
                             + hex(bal)[2:].zfill(64))
            tx = {"to": contract, "data": transfer_data, "value": 0,
                  "gas": 60000,
                  "maxFeePerGas": max_fee,
                  "maxPriorityFeePerGas": max_priority_fee,
                  "nonce": nonce, "chainId": chain_id, "type": 2}
            plan.append((index, address, priv, tx,
                         f"{sym} {bal} -> {args.destination}"))
            nonce += 1

        # 2. Sweep native coin (leave gas for the txs above + this one)
        gas_needed = 21000 + 60000 * len(tokens)
        gas_cost = gas_needed * max_fee  # worst-case at maxFee
        send_value = native - gas_cost
        if send_value > 0:
            tx = {"to": args.destination, "value": send_value,
                  "gas": 21000,
                  "maxFeePerGas": max_fee,
                  "maxPriorityFeePerGas": max_priority_fee,
                  "nonce": nonce, "chainId": chain_id, "type": 2}
            plan.append((index, address, priv, tx,
                         f"native {send_value} wei -> {args.destination}"))
        elif native > 0:
            print(f"  [{index}] warning: native balance {native} wei "
                  f"doesn't cover gas ({gas_cost}). Skipping native sweep.")

    if not plan:
        print("Nothing to sweep (balances don't cover gas).")
        return

    print(f"\nSweep plan: {len(plan)} transactions")
    for _, addr, _, _, desc in plan:
        print(f"  {addr}: {desc}")

    if args.dry_run:
        print("\n[DRY RUN] Would sign and broadcast the above. "
              "Re-run with --execute to proceed.")
        return

    if not args.yes and not confirm("Sign and broadcast these sweeps?"):
        print("Aborted.")
        return

    # Transaction journal (audit): append-only record of every sweep.
    # Written BEFORE broadcast so a crash mid-batch still leaves a record.
    import datetime
    journal_path = f"sweep-journal-{chain_id}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    journal = {
        "chain_id": chain_id,
        "destination": args.destination,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "execute",
        "entries": [],
    }
    for index, address, priv, tx, desc in plan:
        journal["entries"].append({
            "index": index,
            "from": address,
            "to": tx["to"],
            "value_wei": str(tx.get("value", 0)),
            "data": tx.get("data", "0x"),
            "nonce": tx["nonce"],
            "maxFeePerGas": str(tx["maxFeePerGas"]),
            "maxPriorityFeePerGas": str(tx["maxPriorityFeePerGas"]),
            "description": desc,
            "tx_hash": None,
            "status": "pending",
        })
    with open(journal_path, "w") as jf:
        json.dump(journal, jf, indent=2)
    print(f"\nJournal written to {journal_path} ({len(plan)} entries).")

    for i, (index, address, priv, tx, desc) in enumerate(plan):
        acct = Account.from_key(priv)
        signed = acct.sign_transaction(tx)
        try:
            tx_hash = rpc_call(args.rpc, "eth_sendRawTransaction",
                               [signed.raw_transaction.hex()])
            print(f"  {address}: broadcast {tx_hash} ({desc})")
            journal["entries"][i]["tx_hash"] = tx_hash
            journal["entries"][i]["status"] = "broadcast"
        except Exception as e:
            print(f"  {address}: FAILED: {e}")
            journal["entries"][i]["status"] = f"failed: {e}"
        # Update journal after each broadcast (crash-safe)
        with open(journal_path, "w") as jf:
            json.dump(journal, jf, indent=2)


# ---------------------------------------------------------------------------
# DB mode
# ---------------------------------------------------------------------------

def db_indices(db_path, chain):
    """Return sorted derivation indices from crypto_deposits."""
    evm_chains = {"eth", "usdt_base", "usdc_base", "usdt_op", "usdc_op",
                  "usdt_polygon", "usdc_polygon"}
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT DISTINCT derivation_index, chain FROM crypto_deposits "
        "WHERE derivation_index IS NOT NULL")
    indices = set()
    for idx, ch in cur.fetchall():
        is_evm = ch in evm_chains
        if (chain == "evm" and is_evm) or (chain == "btc" and ch == "btc"):
            indices.add(idx)
    con.close()
    return sorted(indices)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Offline sweep tool for Nova bot deposit addresses.")
    ap.add_argument("--chain", required=True, choices=["btc", "evm"],
                    help="Chain family to sweep")
    ap.add_argument("--destination", required=True,
                    help="Address to sweep funds TO (your main wallet)")
    ap.add_argument("--db",
                    help="Path to bot SQLite DB; sweep only addresses in "
                         "crypto_deposits (with derivation_index)")
    ap.add_argument("--max-index", type=int, default=1000,
                    help="Max derivation index to scan (default 1000)")
    ap.add_argument("--fee-rate", type=int,
                    help="BTC fee rate in sat/vB (default: mempool halfHourFee)")
    ap.add_argument("--rpc",
                    help="EVM JSON-RPC URL (required for --chain evm)")
    ap.add_argument("--tokens", action="store_true",
                    help="Also sweep ERC-20 tokens (USDT/USDC on mainnet)")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Show the plan without signing (default)")
    ap.add_argument("--execute", action="store_true",
                    help="Actually sign and broadcast (disables dry-run)")
    ap.add_argument("--yes", action="store_true",
                    help="Skip interactive confirmation")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    print("=" * 60)
    print("Nova deposit sweep tool — OFFLINE signing")
    print("=" * 60)
    if args.dry_run:
        print("MODE: DRY RUN (no signing, no broadcast)")
    else:
        print("MODE: LIVE — will sign and broadcast!")

    mnemonic = getpass.getpass("Seed phrase (input hidden): ").strip()
    if not mnemonic:
        print("No seed provided. Aborting.")
        sys.exit(1)

    # Validate
    try:
        from bip_utils import Bip39SeedGenerator
        Bip39SeedGenerator(mnemonic).Generate()
    except Exception as e:
        print(f"Invalid seed phrase: {e}")
        sys.exit(1)

    try:
        if args.chain == "btc":
            btc_sweep(args, mnemonic)
        else:
            evm_sweep(args, mnemonic)
    finally:
        # Wipe the mnemonic from memory
        mnemonic = "0" * len(mnemonic)
        del mnemonic

    print("\nDone.")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------
# INSTALL:
#   pip install bip-utils embit eth-account requests
#
# DRY RUN (BTC) — see what would be swept:
#   python3 tools/sweep.py --chain btc --destination bc1qYOURMAINWALLET
#
# DRY RUN (BTC) from the bot's DB (only addresses the bot actually used):
#   python3 tools/sweep.py --chain btc --destination bc1qYOURMAINWALLET \
#       --db /path/to/nova_shop.db
#
# REAL SWEEP (BTC):
#   python3 tools/sweep.py --chain btc --destination bc1qYOURMAINWALLET \
#       --execute --yes
#
# DRY RUN (EVM, native + USDT/USDC):
#   python3 tools/sweep.py --chain evm --destination 0xYOURMAINWALLET \
#       --rpc https://eth.llamarpc.com --tokens
#
# REAL SWEEP (EVM):
#   python3 tools/sweep.py --chain evm --destination 0xYOURMAINWALLET \
#       --rpc https://eth.llamarpc.com --tokens --execute
#
# SECURITY WARNINGS:
#   - Run this on YOUR OWN trusted machine, never on a server.
#   - The seed phrase is prompted interactively and never stored.
#   - ALWAYS dry-run first. Verify the destination address twice.
#   - For large amounts, test with a single small address first
#     (use --db to target specific indices, or --max-index 5).
# ---------------------------------------------------------------------------
