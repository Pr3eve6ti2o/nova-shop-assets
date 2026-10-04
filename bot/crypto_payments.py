"""Crypto payments for Nova Shop Bot: CryptoBot rail + self-custody direct deposits.

Money rule: crypto amounts are ALWAYS Python ints in the chain's base unit
(sats / wei-base / sun / nanotons). No floats for money — floats appear only
in the CoinGecko rate feed, converted to int math immediately.

Chains:
  btc - Bitcoin, BIP84 m/84'/0'/0'/0/i, xpub-only derivation (seed stays offline)
  eth - USDT on ERC-20, BIP44 m/44'/60'/0'/0/i (stablecoin: no volatility window)
  trx - USDT on TRC-20, BIP44 m/44'/195'/0'/0/i
  ton - Toncoin, ONE static address + unique memo NOVA-<order_id> (no xpub needed)
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import os
import subprocess
import time

import aiohttp

import config

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ chains ---
CHAINS = {
    "btc": {
        "name": "Bitcoin", "symbol": "BTC", "decimals": 8,
        "confirmations": 3, "button": "\u20bf BTC",
        "xpub_env": "XPUB_BTC", "hd": ("bip84", 0),
    },
    "eth": {
        "name": "USDT (ERC-20)", "symbol": "USDT", "decimals": 6,
        "confirmations": 12, "button": "\u039e USDT (ERC-20)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0xdAC17F958D2e523a2206206994597C13D831ec7",
    },
    "trx": {
        "name": "USDT (TRC-20)", "symbol": "USDT", "decimals": 6,
        "confirmations": 19, "button": "\U0001f53a USDT (TRC-20)",
        "xpub_env": "XPUB_TRX", "hd": ("bip44", 195),
        "token_contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    },
    "ton": {
        "name": "Toncoin", "symbol": "TON", "decimals": 9,
        # NOTE: do NOT use 💎 here — the lexicon reserves 💎 for CryptoBot.
        "confirmations": 1, "button": "\U0001f537 TON",
    },
}

COINGECKO_IDS = {"btc": "bitcoin", "eth": "tether",
                 "trx": "tether", "ton": "the-open-network"}

# Fallback price sources (verified live 2026-09-30 against the sandbox egress).
# Kraken covers all four chains (pair -> last close price). NOTE: the "eth" and
# "trx" chains settle in USDT (ERC-20/TRC-20), so their pairs are USDTZUSD —
# pricing them as ETH/TRX was a critical bug (0.007 USDT for a $20 order).
# Coinbase covers BTC/ETH/TRX/TON via exchange-rates (crypto per 1 USD,
# so USD price = 1 / rate); USDT chains use the USDT symbol.
KRAKEN_PAIRS = {"btc": "XXBTZUSD", "eth": "USDTZUSD",
                "trx": "USDTZUSD", "ton": "TONUSD"}
COINBASE_SYMS = {"btc": "BTC", "eth": "USDT", "trx": "USDT", "ton": "TON"}

# Dust thresholds in base units. A deposit below its chain's dust updates the
# seen amount but never triggers an underpaid user notice (griefing guard).
DUST_BASE_UNITS = {"btc": 1000, "eth": 1000, "trx": 1000, "ton": 1_000_000}

# Accept >= expected - 2% (price moved while the user was sending).
TOLERANCE_NUM = 98
TOLERANCE_DEN = 100

_rates_cache = {"ts": 0.0, "rates": {}}
_RATES_TTL = 300  # 5 minutes: fresh-fetch window
_RATES_STALE_MAX = 1800  # 30 minutes: serve last-good rates this long


def chain_configured(chain: str) -> bool:
    """A chain is usable when its secret is configured (xpub or TON address)."""
    if chain == "ton":
        return bool(config.TON_DEPOSIT_ADDRESS)
    env_key = CHAINS[chain]["xpub_env"]
    return bool(getattr(config, env_key, None))


def enabled_chains() -> list:
    """Chains that are both configured. Per-chain admin toggles live in kv."""
    return [c for c in CHAINS if chain_configured(c)]


# ------------------------------------------------------------ derivation ---
_WALLET_CORE_DERIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "tools", "hdwallet-gen", "derive.js")

def derive_address(chain: str, xpub: str, index: int) -> str:
    """Derive the external-chain address at `index` from an account xpub.

    BTC: m/84'/0'/0'/0/i ; ETH: m/44'/60'/0'/0/i ; TRX: m/44'/195'/0'/0/i.
    `index` 0 is reserved; counting starts at 1.

    The admin supplies the account-level xpub and the bot derives the
    non-hardened child path m/0/<index> — the private key never touches
    the server, so a breach can't steal funds, only see addresses.

    Derivation runs through the OFFICIAL trustwallet/wallet-core
    (trustwallet/wallet-core on GitHub) via tools/hdwallet-gen/derive.js,
    so the addresses users pay to come from Trust Wallet's own code.
    Verified against canonical test vectors in the smoke suite.
    """
    if chain not in ("btc", "eth", "trx"):
        raise ValueError(f"unsupported chain: {chain}")
    if not xpub or not xpub.strip():
        raise ValueError(f"missing xpub for {chain}")
    if not isinstance(index, int) or index < 0:
        raise ValueError(f"bad derivation index: {index}")
    try:
        proc = subprocess.run(
            ["node", _WALLET_CORE_DERIVE, chain, xpub.strip(), str(index)],
            capture_output=True, text=True, timeout=30, cwd=os.path.dirname(_WALLET_CORE_DERIVE),
        )
    except Exception as e:
        raise ValueError(f"wallet-core derive failed for {chain}: {e}") from e
    addr = (proc.stdout or "").strip().split()[0] if proc.stdout else ""
    if proc.returncode != 0 or not addr:
        err = (proc.stderr or "").strip().split("\n")[-1] if proc.stderr else "unknown"
        raise ValueError(f"wallet-core derive failed for {chain}: {err}")
    return addr


async def next_deposit_address(db, chain: str):
    """Allocate the next fresh address for `chain`.

    Returns (address, index, memo). TON returns the static address + memo.
    """
    if chain == "ton":
        return config.TON_DEPOSIT_ADDRESS, 0, None  # memo set per order
    xpub = getattr(config, CHAINS[chain]["xpub_env"])
    index = await db.next_xpub_index(chain)
    return derive_address(chain, xpub, index), index, None


# ------------------------------------------------------------------ money ---
def format_crypto(base_units: int, chain: str) -> str:
    """Format integer base units as a human decimal string. No floats."""
    dec = CHAINS[chain]["decimals"]
    sym = CHAINS[chain]["symbol"]
    whole, frac = divmod(int(base_units), 10 ** dec)
    frac_s = str(frac).zfill(dec).rstrip("0")
    return f"{whole}.{frac_s} {sym}" if frac_s else f"{whole} {sym}"


def usd_cents_to_base_units(usd_cents: int, price_usd: float, chain: str) -> int:
    """Convert USD cents to integer base units at a float price. Round UP.

    price_usd is e.g. 67234.5 (USD per 1 coin). Integer math only after the
    float->cents conversion.
    """
    if price_usd <= 0:
        raise ValueError("bad price")
    dec = CHAINS[chain]["decimals"]
    price_cents = int(round(price_usd * 100))
    # ceil(usd_cents * 10^dec / price_cents)
    num = int(usd_cents) * (10 ** dec)
    return (num + price_cents - 1) // price_cents


def meets_tolerance(seen_base: int, expected_base: int) -> bool:
    return int(seen_base) * TOLERANCE_DEN >= int(expected_base) * TOLERANCE_NUM


# ------------------------------------------------------------------ rates ---
def _proxy():
    import os
    return os.getenv("https_proxy") or os.getenv("HTTPS_PROXY") or None


async def _fetch_coingecko() -> dict:
    """Primary source. Returns {chain: usd float}; raises on any failure."""
    ids = ",".join(COINGECKO_IDS.values())
    url = ("https://api.coingecko.com/api/v3/simple/price"
           f"?ids={ids}&vs_currencies=usd")
    async with aiohttp.ClientSession() as s:
        async with s.get(url, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
    rates = {c: float(data[gid]["usd"])
             for c, gid in COINGECKO_IDS.items()
             if isinstance(data.get(gid), dict) and data[gid].get("usd")}
    if not rates:
        raise RuntimeError("coingecko: empty response")
    return rates


async def _fetch_kraken() -> dict:
    """Fallback 1: Kraken public ticker (no key). Returns {chain: usd float}."""
    pairs = ",".join(KRAKEN_PAIRS.values())
    url = f"https://api.kraken.com/0/public/Ticker?pair={pairs}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
    if data.get("error"):
        raise RuntimeError(f"kraken: {data['error']}")
    result = data.get("result") or {}
    rates = {}
    for chain, pair in KRAKEN_PAIRS.items():
        close = (result.get(pair) or {}).get("c") or [None]
        if close[0]:
            rates[chain] = float(close[0])
    if not rates:
        raise RuntimeError("kraken: no pairs in response")
    return rates


async def _fetch_coinbase() -> dict:
    """Fallback 2: Coinbase exchange rates (no key). Returns {chain: usd float}.

    The endpoint quotes crypto-per-1-USD, so USD price = 1 / rate.
    """
    url = "https://api.coinbase.com/v2/exchange-rates?currency=USD"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
            data = await r.json()
    quoted = (data.get("data") or {}).get("rates") or {}
    rates = {}
    for chain, sym in COINBASE_SYMS.items():
        try:
            per_usd = float(quoted.get(sym) or 0)
        except (TypeError, ValueError):
            continue
        if per_usd > 0:
            rates[chain] = 1.0 / per_usd
    if not rates:
        raise RuntimeError("coinbase: no symbols in response")
    return rates


async def get_rates(force: bool = False) -> dict:
    """USD prices per chain, from CoinGecko with Kraken/Coinbase fallbacks.

    Strategy: CoinGecko first; any chain still missing a price is filled from
    Kraken, then Coinbase. Fresh results are cached 5 min. When every source
    fails, last-good rates are served stale for up to 30 min (logged); older
    than that, returns {} and the caller hides the direct-crypto rail.
    """
    now = time.time()
    if not force and now - _rates_cache["ts"] < _RATES_TTL and _rates_cache["rates"]:
        return _rates_cache["rates"]

    rates: dict = {}
    served_by: dict = {}
    fetchers = (("coingecko", _fetch_coingecko),
                ("kraken", _fetch_kraken),
                ("coinbase", _fetch_coinbase))
    for name, fetch in fetchers:
        missing = [c for c in COINGECKO_IDS if c not in rates]
        if not missing:
            break
        try:
            got = await fetch()
        except Exception as e:
            logger.warning("%s rates failed: %s", name, e)
            continue
        for c in missing:
            if c in got and got[c] > 0:
                rates[c] = got[c]
                served_by[c] = name

    if rates:
        _rates_cache.update(ts=now, rates=rates)
        logger.info("rates served: %s",
                    {c: served_by.get(c, "?") for c in sorted(rates)})
        return rates

    age = now - _rates_cache["ts"]
    if _rates_cache["rates"] and age < _RATES_STALE_MAX:
        logger.warning("all rate sources failed; serving STALE rates (age %.0fs)",
                       age)
        return _rates_cache["rates"]
    logger.error("all rate sources failed and no usable cache; rates empty")
    return {}


# ---------------------------------------------------------------- CryptoBot ---
def _cryptobot_base() -> str:
    return ("https://testnet-pay.crypt.bot/api" if config.CRYPTOBOT_TESTNET
            else "https://pay.crypt.bot/api")


async def _cryptobot_call(method: str, params: dict) -> dict:
    """Raw Crypto Pay API call. Raises on transport/API error."""
    if not config.CRYPTOBOT_TOKEN:
        raise RuntimeError("CRYPTOBOT_TOKEN not configured")
    url = f"{_cryptobot_base()}/{method}"
    headers = {"Crypto-Pay-API-Token": config.CRYPTOBOT_TOKEN}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=25)) as r:
            data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(f"CryptoBot API error: {data}")
    return data["result"]


async def cryptobot_create_invoice(*, order_id: int, usd_cents: int,
                                   asset: str = "USDT") -> dict:
    """Create a CryptoBot invoice: USD total + fee%, rounded UP to cents."""
    fee_pct = config.CRYPTOBOT_FEE_PERCENT
    gross_cents = (int(usd_cents) * (100 + fee_pct) + 99) // 100  # ceil
    amount = f"{gross_cents // 100}.{gross_cents % 100:02d}"
    return await _cryptobot_call("createInvoice", {
        "asset": asset,
        "amount": amount,
        "description": f"Nova Shop order #{order_id}",
        "payload": str(order_id),
        "expires_in": 1800,  # 30 min invoice window
    })


async def cryptobot_get_invoices(invoice_ids=None, status: str = None) -> list:
    params = {}
    if invoice_ids:
        params["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
    if status:
        params["status"] = status
    res = await _cryptobot_call("getInvoices", params)
    return res.get("items", res) if isinstance(res, dict) else res


def verify_cryptobot_webhook(raw_body: bytes, signature: str, token: str) -> bool:
    """Verify Crypto Pay webhook: HMAC_SHA256(key=SHA256(token)) over raw body.

    Optional in this deployment (no public URL), but the code + docs ship so a
    future webhook deployment is one route away.
    """
    if not raw_body or not signature or not token:
        return False
    key = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


# ------------------------------------------------------- chain watchers ---
async def _get_json(url: str, params: dict = None, timeout: int = 20):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            return await r.json()


async def fetch_btc_txs(address: str) -> tuple:
    """Return (txs, tip_height). tx: {txid, to, sats, confirmations}."""
    try:
        txs = await _get_json(f"https://mempool.space/api/address/{address}/txs")
        tip = await _get_json("https://mempool.space/api/blocks/tip/height")
    except Exception as e:
        logger.warning("mempool.space failed (%s), trying blockchain.info", e)
        try:
            data = await _get_json(f"https://blockchain.info/rawaddr/{address}",
                                   params={"limit": 50})
            out = []
            for tx in data.get("txs", []):
                conf = tx.get("block_height")
                conf = 999 if conf else 0
                for o in tx.get("out", []):
                    if o.get("addr") == address:
                        out.append({"txid": tx["hash"], "to": address,
                                    "sats": int(o["value"]), "confirmations": conf})
            return out, 0
        except Exception as e2:
            logger.warning("blockchain.info fallback failed: %s", e2)
            return [], 0
    out = []
    for tx in txs or []:
        h = (tx.get("status") or {}).get("block_height")
        conf = (tip - h + 1) if h and tip else 0
        for vout in tx.get("vout", []):
            if vout.get("scriptpubkey_address") == address:
                out.append({"txid": tx["txid"], "to": address,
                            "sats": int(vout["value"]), "confirmations": conf})
    await asyncio.sleep(1)  # mempool.space: be polite (<=10/min)
    return out, tip or 0


async def fetch_eth_usdt_txs(address: str) -> list:
    """USDT-ERC20 transfers TO address. tx: {txid, to, base, confirmations}."""
    contract = CHAINS["eth"]["token_contract"]
    try:
        data = await _get_json(
            f"https://eth.blockscout.com/api/v2/addresses/{address}/token-transfers",
            params={"type": "ERC-20"})
        stats = await _get_json("https://eth.blockscout.com/api/v2/stats")
        tip = int(stats.get("total_blocks", 0) or 0)
    except Exception as e:
        logger.warning("blockscout failed: %s", e)
        return []
    out = []
    for it in data.get("items", []):
        to = (it.get("to") or {}).get("hash", "")
        tok = (it.get("token") or {}).get("contract", "")
        if to.lower() != address.lower() or tok.lower() != contract.lower():
            continue
        try:
            base = int((it.get("total") or {}).get("value", "0"))
        except (TypeError, ValueError):
            continue
        blk = it.get("block_number") or 0
        conf = (tip - int(blk) + 1) if blk and tip else 0
        out.append({"txid": it.get("transaction_hash", ""), "to": to,
                    "base": base, "confirmations": conf})
    await asyncio.sleep(1)
    return out


async def fetch_trx_usdt_txs(address: str) -> list:
    """USDT-TRC20 transfers TO address via Tronscan."""
    contract = CHAINS["trx"]["token_contract"]
    try:
        data = await _get_json(
            "https://apilist.tronscanapi.com/api/token_trc20/transfers",
            params={"contract_address": contract, "relatedAddress": address,
                    "limit": 50, "sort": "-timestamp"})
        tip_data = await _get_json("https://apilist.tronscanapi.com/api/block",
                                   params={"sort": "-number", "limit": 1})
        tip = int((tip_data.get("data") or [{}])[0].get("number", 0) or 0)
    except Exception as e:
        logger.warning("tronscan failed: %s", e)
        return []
    out = []
    for it in (data.get("data") or []):
        if (it.get("toAddress") or "") != address:
            continue
        try:
            base = int(str(it.get("quant", "0")))
        except (TypeError, ValueError):
            continue
        blk = int(it.get("block") or 0)
        conf = (tip - blk + 1) if blk and tip else 0
        out.append({"txid": it.get("transactionHash", ""), "to": address,
                    "base": base, "confirmations": conf})
    await asyncio.sleep(1)
    return out


async def fetch_ton_txs(address: str) -> list:
    """TON transfers TO address via toncenter.
    tx: {txid, to, source, base, memo, utime}."""
    try:
        data = await _get_json("https://toncenter.com/api/v2/getTransactions",
                               params={"address": address, "limit": 20})
    except Exception as e:
        logger.warning("toncenter failed: %s", e)
        return []
    out = []
    for tx in (data.get("result") or []):
        in_msg = tx.get("in_msg") or {}
        if (in_msg.get("destination") or "") != address:
            continue
        try:
            base = int(str(in_msg.get("value", "0")))
        except (TypeError, ValueError):
            continue
        memo = _decode_ton_comment(in_msg.get("message"))
        txid = tx.get("transaction_id", {}) or {}
        # SECURITY (audit): capture sender + timestamp so callers can verify
        # the claimed sender and enforce a recency window (prevents replay).
        try:
            utime = int(tx.get("utime") or 0)
        except (TypeError, ValueError):
            utime = 0
        out.append({"txid": f"{txid.get('hash', '')}:{txid.get('lt', '')}",
                    "to": address,
                    "source": str(in_msg.get("source") or ""),
                    "base": base, "memo": memo, "utime": utime,
                    "confirmations": 999})  # TON: seen in block == final
    await asyncio.sleep(1)
    return out


def _decode_ton_comment(message) -> str:
    """Decode a toncenter text-comment body to str. Best effort."""
    if not message:
        return ""
    try:
        raw = base64.b64decode(message)
    except Exception:
        return ""
    # Text comments: 4 zero bytes (op=0) + UTF-8 payload.
    if raw[:4] == b"\x00\x00\x00\x00":
        raw = raw[4:]
    try:
        return raw.decode("utf-8", errors="strict").strip().strip("\x00")
    except Exception:
        return ""


# ---------------------------------------------------------------- matching ---
def matching_txs(chain: str, txs: list, address: str,
                 memo: str = None) -> list:
    """All txs paying `address`: address match (case-insensitive), TON memo
    match when a memo is given, amount > 0. Pure and unit-testable."""
    out = []
    for tx in txs:
        if (tx.get("to") or "").lower() != address.lower():
            continue
        if chain == "ton" and memo:
            if (tx.get("memo") or "") != memo:
                continue
        amt = int(tx.get("base", tx.get("sats", 0)) or 0)
        if amt <= 0:
            continue
        out.append(tx)
    return out


def match_deposit(chain: str, txs: list, address: str, expected_base: int,
                  memo: str = None) -> dict:
    """Pure matching logic (unit-testable). Returns the best tx dict or None.

    Best = the largest payment to the address. The caller splits paid vs
    underpaid with meets_tolerance() (98%): an underpaid tx is still
    returned so the watcher can flag it and keep watching until TTL
    instead of going silent. Use matching_txs() + sum when several
    top-up payments must count together.
    """
    best = None
    best_amt = 0
    for tx in matching_txs(chain, txs, address, memo):
        amt = int(tx.get("base", tx.get("sats", 0)) or 0)
        if best is None or amt > best_amt:
            best, best_amt = tx, amt
    return best


# ------------------------------------------------------------- rails list ---
async def payment_rails(db, total_cents: int):
    """Ordered payment rails per SPEC2 §1: (method_id, button_text).

    Order: Stars (always) -> CryptoBot (if token) -> Card (if token) ->
    Direct Crypto (if any chain) -> COD/pickup (label chosen by caller).
    """
    from utils import fmt_money, stars_for_cents
    import texts
    rails = []
    stars_n = stars_for_cents(int(total_cents), config.STARS_PER_USD)
    rails.append(("stars", texts.BTN_STARS.format(n=stars_n)))
    if config.CRYPTOBOT_TOKEN:
        fee = (int(total_cents) * config.CRYPTOBOT_FEE_PERCENT + 99) // 100
        gross = int(total_cents) + fee
        rails.append(("cryptobot", texts.BTN_CRYPTOBOT_RAIL.format(
            total=fmt_money(gross, config.CURRENCY),
            fee_pct=config.CRYPTOBOT_FEE_PERCENT)))
    if config.PAYMENTS_PROVIDER_TOKEN:
        rails.append(("card", texts.BTN_CARD.format(
            total=fmt_money(total_cents, config.CURRENCY))))
    direct_chains = [c for c in enabled_chains()
                     if db is None or await db.crypto_chain_enabled(c)]
    if direct_chains:
        rails.append(("direct", texts.BTN_DIRECT_CRYPTO))
    rails.append(("cod", None))  # label chosen by caller (COD vs pickup)
    return rails
