"""Crypto deposits: scope derivation-index counters per xpub, not per chain.

Audit 20261015 04-crypto (P0). db.next_xpub_index() used to keep one
counter per CHAIN name (kv key xpub_index_<chain>). But every EVM chain
(usdt_base, usdc_base, usdt_op, usdc_op, usdt_polygon, usdc_polygon — and
the legacy eth chain) derives from the SAME XPUB_ETH through the same
derivation path, so index N on any of them yields the identical deposit
address. Per-chain counters all start at 1, so the first order on each
EVM chain was issued the same address as the first order on every other
EVM chain — two live orders sharing one deposit address, with deposits
matched by address.

The counter is now keyed by derivation domain (the xpub's config name).
This migration seeds each scoped counter with the highest index already
issued under the legacy per-chain keys, so no address that has been
handed out is ever reissued. Legacy keys are left in place (audit trail);
they are never read again.
"""

VERSION = 16
DESCRIPTION = "Crypto: seed per-xpub derivation counters from legacy per-chain counters"

# xpub config name -> chain names whose legacy counters fed that domain.
_SCOPES = {
    "XPUB_ETH": ("eth", "usdt_base", "usdc_base", "usdt_op", "usdc_op",
                 "usdt_polygon", "usdc_polygon"),
    "XPUB_BTC": ("btc",),
    "XPUB_TRX": ("trx",),
    "TESTNET_XPUB_ETH": ("teth", "tusdc_base"),
}


async def up(db):
    async with db._db() as conn:
        for env, chains in _SCOPES.items():
            keys = [f"xpub_index_{env}"] + [f"xpub_index_{c}" for c in chains]
            best = 0
            for key in keys:
                async with conn.execute(
                        "SELECT value FROM kv WHERE key=?", (key,)) as cur:
                    row = await cur.fetchone()
                if row and str(row["value"]).isdigit():
                    best = max(best, int(row["value"]))
            if best > 0:
                await conn.execute(
                    "INSERT INTO kv(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (f"xpub_index_{env}", str(best)))
        await conn.commit()
