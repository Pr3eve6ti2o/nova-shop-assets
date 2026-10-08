"""Crypto payments for Nova Shop Bot: CryptoBot rail + self-custody direct deposits.

import os
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
        "token_contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
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
    "usdt_base": {
        "name": "USDT (Base)", "symbol": "USDT", "decimals": 6,
        "confirmations": 12, "button": "USDT (Base)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x102d758f688a4C1C5a80b116bD945d4455460282",
        "blockscout": "https://base.blockscout.com/api/v2",
    },
    "usdc_base": {
        "name": "USDC (Base)", "symbol": "USDC", "decimals": 6,
        "confirmations": 12, "button": "USDC (Base)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "blockscout": "https://base.blockscout.com/api/v2",
    },
    "usdt_op": {
        "name": "USDT (Optimism)", "symbol": "USDT", "decimals": 6,
        "confirmations": 12, "button": "USDT (Optimism)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x94b008aA00579c1307B0EF2c499aD98a8Ce58e58",
        "blockscout": "https://optimism.blockscout.com/api/v2",
    },
    "usdc_op": {
        "name": "USDC (Optimism)", "symbol": "USDC", "decimals": 6,
        "confirmations": 12, "button": "USDC (Optimism)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "blockscout": "https://optimism.blockscout.com/api/v2",
    },
    "usdt_polygon": {
        "name": "USDT (Polygon)", "symbol": "USDT", "decimals": 6,
        "confirmations": 12, "button": "USDT (Polygon)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
        "blockscout": "https://polygon.blockscout.com/api/v2",
    },
    "usdc_polygon": {
        "name": "USDC (Polygon)", "symbol": "USDC", "decimals": 6,
        "confirmations": 12, "button": "USDC (Polygon)",
        "xpub_env": "XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "blockscout": "https://polygon.blockscout.com/api/v2",
    },
}

# ---------------------------------------------------------------------------
# TESTNET chains (enabled with CRYPTO_TESTNET=1).
# Structure mirrors CHAINS exactly so deposit flow / watcher / formatting work
# unchanged. All names & buttons carry a TESTNET marker.
# ---------------------------------------------------------------------------
TESTNET_CHAINS = {
    "teth": {
        "name": "TESTNET tETH (Sepolia)", "symbol": "tETH", "decimals": 18,
        "confirmations": 3, "button": "\U0001f9ea TESTNET tETH (Sepolia)",
        "xpub_env": "TESTNET_XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": None,  # native coin -> watcher uses txlist
        "chain_id": 11155111,
        "blockscout": "https://eth-sepolia.blockscout.com/api/v2",
    },
    "tusdc_base": {
        "name": "TESTNET tUSDC (Base Sepolia)", "symbol": "tUSDC", "decimals": 6,
        "confirmations": 3, "button": "\U0001f9ea TESTNET tUSDC (Base Sepolia)",
        "xpub_env": "TESTNET_XPUB_ETH", "hd": ("bip44", 60),
        "token_contract": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "chain_id": 84532,
        "blockscout": "https://base-sepolia.blockscout.com/api/v2",
    },
}


def is_testnet() -> bool:
    """True when the bot runs in CRYPTO_TESTNET mode."""
    return bool(getattr(config, "CRYPTO_TESTNET", False))


def active_chains() -> dict:
    """Single source of truth for chain metadata used across the bot."""
    return TESTNET_CHAINS if is_testnet() else CHAINS


EVM_CHAINS = frozenset({
    "eth", "usdt_base", "usdc_base", "usdt_op", "usdc_op",
    "usdt_polygon", "usdc_polygon",
}) | frozenset(TESTNET_CHAINS.keys())
LEGACY_CHAINS = frozenset({"eth", "trx"})
STABLECOIN_CHAINS = frozenset({
    "eth", "trx", "usdt_base", "usdc_base", "usdt_op", "usdc_op",
    "usdt_polygon", "usdc_polygon",
})

TON_FINALITY_CONFIRMATIONS = 1

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
    if chain not in CHAINS:
        return False
    env_key = active_chains()[chain]["xpub_env"]
    return bool(getattr(config, env_key, None))


def enabled_chains() -> list:
    """Chains that are both configured. Per-chain admin toggles live in kv."""
    return [c for c in CHAINS if c not in LEGACY_CHAINS and chain_configured(c)]


# ------------------------------------------------------------ derivation ---
# C2: the wallet-core WASM engine used to be recompiled on EVERY checkout
# (~700ms per derivation). _DerivationEngine below keeps ONE persistent Node
# process per bot lifetime and serves derivations over a JSON-line protocol,
# so each checkout derivation costs a few milliseconds.
_WALLET_CORE_DAEMON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "tools", "hdwallet-gen", "derive_daemon.js")

import json as _json
import select as _select
import threading as _threading


class _DerivationEngine:
    """Session-cached wallet-core derivation engine.

    Spawns `node derive_daemon.js` once and reuses it for every derivation.
    Thread-safe: derive_address() is a sync function called from the bot's
    event loop, so a lock serializes requests over the single stdio pipe.
    If the daemon dies, it is restarted once and the request retried; a
    second failure raises, same as the old one-shot path.
    """

    _READY_TIMEOUT = 60
    _REQUEST_TIMEOUT = 30

    def __init__(self):
        self._lock = _threading.Lock()
        self._proc = None

    def _readline(self, stream, timeout):
        r, _, _ = _select.select([stream], [], [], timeout)
        if not r:
            raise TimeoutError("derivation daemon response timeout")
        line = stream.readline()
        if not line:
            raise ConnectionError("derivation daemon closed the pipe")
        return line

    def _spawn(self):
        proc = subprocess.Popen(
            ["node", _WALLET_CORE_DAEMON],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(_WALLET_CORE_DAEMON),
            text=False,
            bufsize=0,
        )
        try:
            line = self._readline(proc.stdout, self._READY_TIMEOUT)
            hello = _json.loads(line)
            if not hello.get("ready"):
                raise RuntimeError("daemon did not signal ready")
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            raise
        return proc

    def _ensure(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = self._spawn()
        return self._proc

    def derive(self, chain: str, xpub: str, index: int) -> str:
        payload = _json.dumps(
            {"chain": chain, "xpub": xpub.strip(), "index": index}) + "\n"
        last_err = None
        for attempt in range(2):
            try:
                with self._lock:
                    proc = self._ensure()
                    proc.stdin.write(payload.encode())
                    proc.stdin.flush()
                    line = self._readline(proc.stdout, self._REQUEST_TIMEOUT)
                resp = _json.loads(line)
                if resp.get("ok"):
                    return resp["address"]
                raise ValueError(f"wallet-core derive failed for {chain}: "
                                 f"{resp.get('error', 'unknown daemon error')}")
            except (TimeoutError, ConnectionError, BrokenPipeError,
                    _json.JSONDecodeError, RuntimeError) as e:
                last_err = str(e)
            # Transport failure: drop the dead daemon so the next attempt
            # (or next call) spawns a fresh one.
            try:
                if self._proc is not None:
                    self._proc.kill()
            except Exception:
                pass
            self._proc = None
        raise ValueError(f"wallet-core derive failed for {chain}: {last_err}")


_ENGINE = _DerivationEngine()


def derive_address(chain: str, xpub: str, index: int) -> str:
    """Derive the external-chain address at `index` from an account xpub.

    BTC: m/84'/0'/0'/0/i ; ETH: m/44'/60'/0'/0/i ; TRX: m/44'/195'/0'/0/i.
    `index` 0 is reserved; counting starts at 1.

    The admin supplies the account-level xpub and the bot derives the
    non-hardened child path m/0/<index> — the private key never touches
    the server, so a breach can't steal funds, only see addresses.

    Derivation runs through the OFFICIAL trustwallet/wallet-core
    (trustwallet/wallet-core on GitHub) via a persistent
    tools/hdwallet-gen/derive_daemon.js engine (loaded once per bot
    lifetime), so the addresses users pay to come from Trust Wallet's own
    code. Verified against canonical test vectors in the smoke suite.
    """
    daemon_chain = "eth" if chain in EVM_CHAINS else chain
    if daemon_chain not in ("btc", "eth", "trx"):
        raise ValueError(f"unsupported chain: {chain}")
    if not xpub or not xpub.strip():
        raise ValueError(f"missing xpub for {chain}")
    if not isinstance(index, int) or index < 0 or index > 2147483647:
        # C1: 2^31-1 is the BIP32 non-hardened max. Index 0 is cryptographically
        # valid (test vectors use it); the bot reserves it via next_xpub_index
        # which starts allocation at 1.
        raise ValueError(f"bad derivation index: {index}")
    # H1: the xpub travels inside the daemon request body (stdin pipe),
    # never in argv (/proc cmdline is world-readable).
    return _ENGINE.derive(daemon_chain, xpub, index)


async def next_deposit_address(db, chain: str):
    """Allocate the next fresh address for `chain`.

    Returns (address, index, memo). TON returns the static address + memo.
    """
    if chain == "ton":
        return config.TON_DEPOSIT_ADDRESS, 0, None  # memo set per order
    xpub = getattr(config, active_chains()[chain]["xpub_env"])
    index = await db.next_xpub_index(chain)
    address = await asyncio.to_thread(derive_address, chain, xpub, index)
    return address, index, None


# ------------------------------------------------------------------ money ---
def format_crypto(base_units: int, chain: str) -> str:
    """Format integer base units as a human decimal string. No floats."""
    if base_units < 0:
        raise ValueError("base_units must be non-negative")
    dec = active_chains()[chain]["decimals"]
    sym = active_chains()[chain]["symbol"]
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
    dec = active_chains()[chain]["decimals"]
    price_cents = int(round(price_usd * 100))
    if price_cents <= 0:
        raise ValueError("bad price")
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
    pairs = ",".join(dict.fromkeys(KRAKEN_PAIRS.values()))
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

    rates: dict = {c: 1.0 for c in STABLECOIN_CHAINS}
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
            if c not in got or got[c] <= 0:
                continue
            v = got[c]
            if not (0.000001 < v < 100_000_000):
                logger.warning("%s rate out of bounds for %s: %s", name, c, v)
                continue
            prev = _rates_cache["rates"].get(c)
            if prev and (v > prev * 10 or v < prev / 10):
                logger.warning("%s rate outlier for %s: %s (prev %s)",
                               name, c, v, prev)
                continue
            rates[c] = v
            served_by[c] = name

    if rates:
        if all(c in rates for c in COINGECKO_IDS):
            _rates_cache.update(ts=now, rates=rates)
            logger.info("rates served: %s",
                        {c: served_by.get(c, "?") for c in sorted(rates)})
        else:
            # H7: fill the gaps from usable stale cache entries (age < 30m)
            # so a partially-failed fetch doesn't drop a chain entirely.
            # The stale entries keep their original age: the merged result is
            # NOT re-cached, so they expire on their own schedule.
            age = now - _rates_cache["ts"]
            if _rates_cache["rates"] and age < _RATES_STALE_MAX:
                for c in COINGECKO_IDS:
                    if c not in rates and c in _rates_cache["rates"]:
                        rates[c] = _rates_cache["rates"][c]
                logger.info("rates partial+stale (not cached): %s",
                            {c: served_by.get(c, "stale") for c in sorted(rates)})
            else:
                logger.info("rates partial (not cached): %s",
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
        async with s.post(url, json=params, headers=headers, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=25)) as r:
            r.raise_for_status()
            data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(f"CryptoBot API error: {data}")
    return data["result"]


async def cryptobot_create_invoice(*, order_id: int, usd_cents: int,
                                   asset: str = "USDT",
                                   note: str = None,
                                   payload: str = None) -> dict:
    """Create a CryptoBot invoice: USD total + fee%, rounded UP to cents."""
    fee_pct = config.CRYPTOBOT_FEE_PERCENT
    if not isinstance(fee_pct, int) or not (0 <= fee_pct < 100):
        raise ValueError("CRYPTOBOT_FEE_PERCENT must be an integer in [0, 100)")
    # Gross up: the fee is charged on the gross invoice amount, so
    # gross = ceil(net * 100 / (100 - fee_pct)).
    gross_cents = ((int(usd_cents) * 100 + (100 - fee_pct) - 1)
                   // (100 - fee_pct))
    amount = f"{gross_cents // 100}.{gross_cents % 100:02d}"
    return await _cryptobot_call("createInvoice", {
        "asset": asset,
        "amount": amount,
        "description": note or f"Nova Shop order #{order_id}",
        "payload": payload or str(order_id),
        "expires_in": 1800,  # 30 min invoice window
    })


async def cryptobot_delete_invoice(invoice_id: int) -> dict:
    """Cancel a CryptoBot invoice (used to dedupe multiple invoices per order)."""
    iid = int(invoice_id)
    if iid <= 0:
        raise ValueError("invoice_id must be positive")
    return await _cryptobot_call("deleteInvoice", {"invoice_id": iid})


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


async def _get_text(url: str, params: dict = None, timeout: int = 20):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, proxy=_proxy(),
                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            r.raise_for_status()
            return await r.text()


async def fetch_btc_txs(address: str) -> tuple:
    """Return (txs, tip_height). tx: {txid, to, sats, confirmations}."""
    try:
        txs = []
        after = None
        while True:
            url = f"https://mempool.space/api/address/{address}/txs"
            if after:
                url += f"/chain/{after}"
            page = await _get_json(url)
            if not page:
                break
            txs.extend(page)
            if sum(1 for tx in page if (tx.get("status") or {}).get("confirmed")) < 25:
                break
            after = page[-1].get("txid")
            if not after:
                break
        tip = int((await _get_text("https://mempool.space/api/blocks/tip/height")).strip())
    except Exception as e:
        logger.warning("mempool.space failed (%s), trying blockchain.info", e)
        try:
            tip_data = await _get_json("https://blockchain.info/latestblock")
            tip = int(tip_data.get("height") or 0)
            data = await _get_json(f"https://blockchain.info/rawaddr/{address}",
                                   params={"limit": 50})
            out = []
            for tx in data.get("txs", []):
                h = tx.get("block_height")
                conf = (tip - h + 1) if h and tip else 0
                for o in tx.get("out", []):
                    if o.get("addr") == address:
                        out.append({"txid": tx["hash"], "to": address,
                                    "sats": int(o["value"]), "confirmations": conf})
            return out, tip
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


async def fetch_evm_token_txs(address: str, blockscout_base: str,
                              contract: str) -> list:
    """ERC-20 token transfers TO address via Blockscout v2.
    tx: {txid, to, base, confirmations}."""
    try:
        items = []
        params = {"type": "ERC-20"}
        while True:
            data = await _get_json(
                f"{blockscout_base}/addresses/{address}/token-transfers",
                params=params)
            items.extend(data.get("items", []))
            next_params = data.get("next_page_params")
            if not next_params:
                break
            params = {"type": "ERC-20", **next_params}
        stats = await _get_json(f"{blockscout_base}/stats")
        tip = int(stats.get("total_blocks", 0) or 0)
    except Exception as e:
        logger.warning("blockscout failed (%s): %s", blockscout_base, e)
        return []
    out = []
    for it in items:
        to = (it.get("to") or {}).get("hash", "")
        tok = (it.get("token") or {}).get("address", "")
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


_ETHERSCAN_V2_API = "https://api.etherscan.io/v2/api"

# Etherscan V2 chain ids (one free key covers every chain, selected via
# `chainid`). Mirrors the blockscout entries in CHAINS.
ETHERSCAN_CHAIN_IDS = {
    "usdt_base": 8453,
    "usdc_base": 8453,
    "usdt_op": 10,
    "usdc_op": 10,
    "usdt_polygon": 137,
    "usdc_polygon": 137,
}


def _etherscan_api_key() -> str:
    """Etherscan V2 key: config.py constant first, env as a safety net.

    Local import keeps this module importable without config (same trick as
    _proxy())."""
    import os
    key = ""
    try:
        import config
        key = (getattr(config, "ETHERSCAN_API_KEY", "") or "").strip()
    except Exception:
        key = ""
    return key or (os.getenv("ETHERSCAN_API_KEY", "") or "").strip()


async def fetch_etherscan_v2_token_txs(address: str, chain_id: int,
                                       contract: str, api_key: str) -> list:
    """ERC-20 token transfers TO address via the Etherscan V2 unified API.

    Fallback for the Blockscout v2 endpoints that Cloudflare 403s
    (polygon.blockscout.com / base.blockscout.com). Output shape is identical
    to fetch_evm_token_txs: tx: {txid, to, base, confirmations}.
    Never raises — returns whatever was collected (possibly [])."""
    if not api_key:
        return []
    out = []
    offset = 1000
    for page in range(1, 11):  # max 10 pages x 1000
        params = {
            "chainid": chain_id,
            "module": "account",
            "action": "tokentx",
            "address": address,
            "contractaddress": contract,
            "page": page,
            "offset": offset,
            "sort": "asc",
            "apikey": api_key,
        }
        items = None
        for attempt in (0, 1):
            data = None
            try:
                data = await _get_json(_ETHERSCAN_V2_API, params=params,
                                       timeout=30)
            except Exception as e:
                logger.warning("etherscan v2 request failed "
                               "(chainid=%s page=%s): %s", chain_id, page, e)
            if not isinstance(data, dict):
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                logger.warning("etherscan v2 unreachable (chainid=%s page=%s)",
                               chain_id, page)
                return out
            status = str(data.get("status", "") or "")
            message = str(data.get("message", "") or "")
            result = data.get("result")
            if status == "1" and isinstance(result, list):
                items = result
                break
            if "no transactions found" in message.lower():
                return out
            if attempt == 0:
                # NOTOK / "Max rate limit reached" -> one retry after 1s.
                await asyncio.sleep(1)
                continue
            logger.warning("etherscan v2 error (chainid=%s page=%s): "
                           "status=%s message=%s result=%s",
                           chain_id, page, status, message, result)
            return out
        if not items:
            break
        for it in items:
            to = it.get("to") or ""
            tok = it.get("contractAddress") or ""
            if to.lower() != address.lower() or tok.lower() != contract.lower():
                continue
            if str(it.get("txreceipt_status", "1") or "1") == "0":
                continue
            try:
                base = int(it.get("value", "0") or "0")
            except (TypeError, ValueError):
                continue
            try:
                conf = int(it.get("confirmations", 0) or 0)
            except (TypeError, ValueError):
                conf = 0
            out.append({"txid": it.get("hash", ""), "to": to,
                        "base": base, "confirmations": conf})
        if len(items) < offset:
            break
        await asyncio.sleep(0.25)
    return out


async def fetch_etherscan_v2_native_txs(address: str, chain_id: int,
                                        api_key: str) -> list:
    """Native-coin transfers TO address via Etherscan V2 (txlist).

    Used for testnet tETH. tx: {txid, to, base, confirmations}.
    Never raises; returns [] on any failure.
    """
    if not api_key or not address:
        return []
    out = []
    for page in range(1, 11):
        params = {
            "chainid": chain_id,
            "module": "account",
            "action": "txlist",
            "address": address,
            "page": page,
            "offset": 1000,
            "sort": "asc",
            "apikey": api_key,
        }
        items = None
        for attempt in (0, 1):
            data = None
            try:
                data = await _get_json(_ETHERSCAN_V2_API, params=params,
                                       timeout=30)
            except Exception as e:
                logger.warning("etherscan v2 native request failed "
                               "(chainid=%s page=%s): %s", chain_id, page, e)
            if not isinstance(data, dict):
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
                logger.warning("etherscan v2 native unreachable "
                               "(chainid=%s page=%s)", chain_id, page)
                return out
            status = str(data.get("status", "") or "")
            message = str(data.get("message", "") or "")
            result = data.get("result")
            if status == "1" and isinstance(result, list):
                items = result
                break
            if "no transactions found" in message.lower():
                return out
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            logger.warning("etherscan v2 native error (chainid=%s page=%s): "
                           "status=%s message=%s",
                           chain_id, page, status, message)
            return out
        if not items:
            break
        for it in items:
            to = it.get("to") or ""
            if to.lower() != address.lower():
                continue
            if str(it.get("txreceipt_status", "1") or "1") == "0":
                continue
            if str(it.get("isError", "0") or "0") == "1":
                continue
            try:
                base = int(it.get("value", "0") or "0")
            except (TypeError, ValueError):
                continue
            if base <= 0:
                continue
            try:
                conf = int(it.get("confirmations", 0) or 0)
            except (TypeError, ValueError):
                conf = 0
            out.append({"txid": it.get("hash", ""), "to": to,
                        "base": base, "confirmations": conf})
        if len(items) < 1000:
            break
        await asyncio.sleep(0.25)
    return out


async def fetch_evm_token_txs_with_fallback(address: str, blockscout_base: str,
                                            contract: str,
                                            chain_id: int) -> list:
    """Blockscout v2 first (keyless), Etherscan V2 as fallback.

    polygon.blockscout.com / base.blockscout.com are 403'd by Cloudflare, so
    USDT/USDC deposits on Polygon/Base only become visible through Etherscan.
    Returns non-empty txs or []."""
    txs = await fetch_evm_token_txs(address, blockscout_base, contract)
    if txs:
        return txs
    api_key = _etherscan_api_key()
    if not api_key:
        logger.warning("blockscout empty and ETHERSCAN_API_KEY unset "
                       "(chainid=%s address=%s)", chain_id, address)
        return []
    txs = await fetch_etherscan_v2_token_txs(address, chain_id, contract,
                                             api_key)
    if txs:
        logger.info("etherscan v2 fallback recovered %d tx(s) (chainid=%s)",
                    len(txs), chain_id)
    return txs


async def fetch_eth_usdt_txs(address: str) -> list:
    """USDT-ERC20 transfers TO address. tx: {txid, to, base, confirmations}."""
    return await fetch_evm_token_txs(
        address, "https://eth.blockscout.com/api/v2",
        CHAINS["eth"]["token_contract"])


async def fetch_trx_usdt_txs(address: str) -> list:
    """USDT-TRC20 transfers TO address via Tronscan."""
    contract = CHAINS["trx"]["token_contract"]
    try:
        items = []
        start = 0
        limit = 50
        while True:
            data = await _get_json(
                "https://apilist.tronscanapi.com/api/token_trc20/transfers",
                params={"contract_address": contract, "relatedAddress": address,
                        "limit": limit, "start": start, "sort": "-timestamp"})
            page = data.get("data") or []
            items.extend(page)
            if len(page) < limit:
                break
            start += limit
        tip_data = await _get_json("https://apilist.tronscanapi.com/api/block",
                                   params={"sort": "-number", "limit": 1})
        tip = int((tip_data.get("data") or [{}])[0].get("number", 0) or 0)
    except Exception as e:
        logger.warning("tronscan failed: %s", e)
        return []
    out = []
    for it in items:
        if (it.get("tokenAddress") or "") != contract:
            continue
        if (it.get("toAddress") or "") != address:
            continue
        try:
            base = int(str(it.get("quant", "0")))
        except (TypeError, ValueError):
            continue
        blk = int(it.get("block") or 0)
        conf = (tip - blk + 1) if blk and tip else 0
        out.append({"txid": it.get("transactionHash", ""), "to": it.get("toAddress"),
                    "base": base, "confirmations": conf})
    await asyncio.sleep(1)
    return out


def _ton_raw(address: str) -> str:
    """Normalize a TON address to canonical raw 'workchain:hex' form; '' if unparseable."""
    if not address:
        return ""
    addr = address.strip()
    if not addr:
        return ""
    if ":" in addr:
        wc, _, h = addr.partition(":")
        try:
            wc_i = int(wc)
        except (TypeError, ValueError):
            return ""
        h = h.strip().lower()
        if len(h) == 64 and all(c in "0123456789abcdef" for c in h):
            return f"{wc_i}:{h}"
        return ""
    try:
        raw = base64.urlsafe_b64decode(addr + "=" * (-len(addr) % 4))
    except Exception:
        return ""
    if len(raw) != 36:
        return ""
    import binascii
    if binascii.crc_hqx(raw[:34], 0) != int.from_bytes(raw[34:36], "big"):
        return ""
    wc = raw[1]
    if wc >= 128:
        wc -= 256
    return f"{wc}:{raw[2:34].hex()}"


async def fetch_ton_txs(address: str) -> list:
    """TON transfers TO address via toncenter.
    tx: {txid, to, source, base, memo, utime}."""
    out = []
    seen = set()
    limit = 100
    lt = None
    tx_hash = None
    for _ in range(100):
        params = {"address": address, "limit": limit}
        if lt is not None and tx_hash is not None:
            params["lt"] = lt
            params["hash"] = tx_hash
        try:
            data = await _get_json(
                "https://toncenter.com/api/v2/getTransactions",
                params=params)
        except Exception as e:
            logger.warning("toncenter failed: %s", e)
            break
        page = data.get("result") or []
        for tx in page:
            in_msg = tx.get("in_msg") or {}
            if _ton_raw(in_msg.get("destination") or "") != _ton_raw(address):
                continue
            try:
                base = int(str(in_msg.get("value", "0")))
            except (TypeError, ValueError):
                continue
            memo = str(in_msg.get("message") or "").strip().strip("\x00")
            txid = tx.get("transaction_id", {}) or {}
            tx_key = f"{txid.get('hash', '')}:{txid.get('lt', '')}"
            if tx_key in seen:
                continue
            seen.add(tx_key)
            # SECURITY (audit): capture sender + timestamp so callers can verify
            # the claimed sender and enforce a recency window (prevents replay).
            try:
                utime = int(tx.get("utime") or 0)
            except (TypeError, ValueError):
                utime = 0
            out.append({"txid": tx_key,
                        "to": address,
                        "source": str(in_msg.get("source") or ""),
                        "base": base, "memo": memo, "utime": utime,
                        "confirmations": TON_FINALITY_CONFIRMATIONS})  # TON: seen in block == final
        if len(page) < limit:
            break
        last_id = (page[-1].get("transaction_id", {}) or {})
        lt = last_id.get("lt")
        tx_hash = last_id.get("hash")
        if not lt or not tx_hash:
            break
        await asyncio.sleep(1)
    await asyncio.sleep(1)
    return out


# ---------------------------------------------------------------- matching ---
def matching_txs(chain: str, txs: list, address: str,
                 memo: str = None) -> list:
    """All txs paying `address`: address match (case-insensitive), TON memo
    match when a memo is given, amount > 0. Pure and unit-testable."""
    out = []
    for tx in txs:
        if chain == "ton":
            if _ton_raw(tx.get("to") or "") != _ton_raw(address):
                continue
        elif chain == "trx":
            if (tx.get("to") or "") != address:
                continue
        elif chain == "eth":
            if (tx.get("to") or "").lower() != address.lower():
                continue
        else:
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
    underpaid with meets_tolerance() (98%): an underpaid deposit stays in the
    sweep until its TTL instead of going silent. Use matching_txs() + sum when
    several top-up payments must count together.
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
    """Ordered payment rails: (method_id, button_text)."""
    from utils import fmt_money, stars_for_cents
    import texts
    stars_n = stars_for_cents(int(total_cents), config.STARS_PER_USD)
    rails = [
        ("balance", texts.BTN_PAY_WITH_BALANCE),
        ("stars", texts.BTN_STARS.format(n=stars_n)),
    ]
    if config.CRYPTOBOT_TOKEN:
        fee_pct = config.CRYPTOBOT_FEE_PERCENT
        if not isinstance(fee_pct, int) or not (0 <= fee_pct < 100):
            raise ValueError("CRYPTOBOT_FEE_PERCENT must be an integer in [0, 100)")
        rails.append(("cryptobot", texts.BTN_CRYPTOBOT))
    if config.PAYMENTS_PROVIDER_TOKEN:
        rails.append(("card", texts.BTN_CARD.format(
            total=fmt_money(total_cents, config.CURRENCY))))
    rails.append(("crypto", texts.BTN_CRYPTO_PAYMENT))
    return rails
