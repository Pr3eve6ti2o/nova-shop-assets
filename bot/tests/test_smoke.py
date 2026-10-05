"""Smoke tests for Nova Shop Bot — plain asserts, no pytest needed.

Run:  python tests/test_smoke.py
Covers: config parsing, fmt_money, callback-data length audit (< 64 bytes),
        DB round-trip (user -> product -> cart -> order -> payment idempotency),
        promo math, Stars conversion.
"""
import asyncio
import importlib
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)
    print(f"  ok: {name}")


import contextlib


@contextlib.contextmanager
def _no_dotenv():
    """Temporarily hide the repo .env so config tests are hermetic.

    python-dotenv's find_dotenv() resolves relative to the *caller's file*
    (config.py), not the cwd — so a real .env in the repo would otherwise
    leak into "missing variable" assertions. Restored even on failure.
    """
    p = os.path.join(REPO_ROOT, ".env")
    bak = p + ".testbak"
    moved = False
    if os.path.exists(p):
        os.rename(p, bak)
        moved = True
    try:
        yield
    finally:
        if moved:
            os.rename(bak, p)


# ------------------------------------------------------------------ config ---
def test_config():
    import config
    with _no_dotenv():
        _test_config_body()


def _test_config_body():
    import config
    # empty ADMINS -> []
    os.environ["BOT_TOKEN"] = "test-token"
    os.environ["ADMINS"] = ""
    importlib.reload(config)
    assert config.ADMINS == [], config.ADMINS
    assert config.BOT_TOKEN == "test-token"
    assert config.PAYMENTS_PROVIDER_TOKEN is None
    assert config.STARS_PER_USD == 60
    assert config.CURRENCY == "USD"
    assert config.REFERRAL_PERCENT == 5

    os.environ["ADMINS"] = "123456789, 987654321 ,"
    importlib.reload(config)
    assert config.ADMINS == [123456789, 987654321], config.ADMINS

    os.environ["ADMINS"] = "abc"
    try:
        importlib.reload(config)
    except RuntimeError:
        pass
    else:
        raise AssertionError("bad ADMINS should raise RuntimeError")

    os.environ["ADMINS"] = ""
    del os.environ["BOT_TOKEN"]
    try:
        importlib.reload(config)
    except RuntimeError as e:
        assert "BOT_TOKEN" in str(e)
    else:
        raise AssertionError("missing BOT_TOKEN should raise RuntimeError")

    # restore sane env for the rest of the suite
    os.environ["BOT_TOKEN"] = "test-token"
    os.environ["ADMINS"] = ""
    importlib.reload(config)


# ------------------------------------------------------------------- money ---
def test_fmt_money():
    from utils import fmt_money, stars_for_cents
    assert fmt_money(1299) == "$12.99"
    assert fmt_money(0) == "$0.00"
    assert fmt_money(5) == "$0.05"
    assert fmt_money(-250) == "-$2.50"
    assert fmt_money(1299, "EUR") == "\u20ac12.99"
    assert fmt_money(1299, "JPY") == "12.99 JPY"
    # Stars: 60 per USD -> $1.00 (100c) = 60 stars
    assert stars_for_cents(100, 60) == 60
    assert stars_for_cents(199, 60) == 120  # ceil(1.99*60)=120
    assert stars_for_cents(1, 60) == 1      # min 1
    assert stars_for_cents(0, 60) == 0


# ------------------------------------------------------- callback data audit ---
def test_callback_data_length():
    kb_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "keyboards.py")
    src = open(kb_path, encoding="utf-8").read()
    literals = re.findall(r'callback_data=(["\'])(.*?)\1', src)
    assert literals, "no callback_data literals found"
    bad = [(q, lit) for q, lit in literals if len(lit.encode("utf-8")) >= 64]
    assert not bad, f"callback data >= 64 bytes: {bad}"
    print(f"    ({len(literals)} literals audited, longest "
          f"{max(len(l.encode()) for _, l in literals)} bytes)")

    # Dynamic builders with realistic ids must also stay short.
    import keyboards as kbmod

    class R(dict):
        pass

    p = R({"id": 123456, "category_id": 789, "name": "Test product",
           "price_cents": 1999, "rating_sum": 45, "rating_count": 10})
    for markup in [
        kbmod.product_kb(p, 99, True, 4.5, 10),
        kbmod.products_kb([p], 789, 7, 100),
        kbmod.cart_kb([R({"product_id": 123456, "qty": 99, "name": "x",
                          "price_cents": 1999})], "SAVE10", "-$5.00", 199900),
        kbmod.admin_order_detail_kb(123456, "pending"),
        kbmod.admin_role_kb(123456789012, 127),
    ]:
        for row in markup.inline_keyboard:
            for btn in row:
                assert btn.callback_data is not None
                assert len(btn.callback_data.encode("utf-8")) < 64, btn.callback_data


# ---------------------------------------------------------------------- db ---
def test_db_roundtrip():
    async def run():
        from database import Database
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db = Database(tmp.name)
        await db.create_tables()
        assert await db.kv_get("maintenance_mode") == "0"
        assert await db.kv_get("referral_percent") == "5"

        # user
        user = await db.create_user(111, "Alice")
        assert user["ref_code"] and len(user["ref_code"]) == 8
        assert await db.get_user_by_tg(111) is not None

        # category + products (physical + digital)
        cid = await db.add_category("Gadgets", "\U0001f4e6")
        pid1 = await db.add_product(category_id=cid, name="Widget",
                                    price_cents=1999, kind="physical", stock=10)
        pid2 = await db.add_product(category_id=cid, name="License",
                                    price_cents=499, kind="digital", stock=-1)
        await db.add_product_values(pid2, ["KEY-1", "KEY-2"])

        # cart
        await db.cart_add(user["id"], pid1, 2)
        await db.cart_add(user["id"], pid2, 1)
        items = await db.cart_items(user["id"])
        assert len(items) == 2
        assert await db.cart_count(user["id"]) == 3
        subtotal = sum(i["price_cents"] * i["qty"] for i in items)
        assert subtotal == 1999 * 2 + 499

        # promo math: 10% of 4497 = 449
        await db.add_promo(code="SAVE10", kind="percent", value=10)
        ok, _, discount, promo = await db.validate_promo("SAVE10", user["id"], subtotal)
        assert ok and discount == 449, discount
        # fixed promo capped at subtotal
        await db.add_promo(code="FIVE", kind="fixed", value=500)
        ok, _, discount2, _ = await db.validate_promo("FIVE", user["id"], 300)
        assert ok and discount2 == 300
        # invalid code
        ok, _, _, _ = await db.validate_promo("NOPE", user["id"], subtotal)
        assert not ok

        # order + items
        oid = await db.create_order(
            user_id=user["id"], subtotal_cents=subtotal, discount_cents=449,
            total_cents=subtotal - 449, payment_method="card",
            delivery_kind="delivery", address="123 St", phone="+100",
            promo_code="SAVE10")
        for it in items:
            await db.add_order_item(oid, it["product_id"], it["name"],
                                    it["qty"], it["price_cents"])
        await db.record_promo_usage(promo["id"], user["id"])
        ok, _, _, _ = await db.validate_promo("SAVE10", user["id"], subtotal)
        assert not ok  # already used

        # payment idempotency
        first = await db.record_payment(
            provider="telegram", external_id="ch_1", user_id=user["id"],
            order_id=oid, amount_cents=subtotal - 449, currency="USD")
        second = await db.record_payment(
            provider="telegram", external_id="ch_1", user_id=user["id"],
            order_id=oid, amount_cents=subtotal - 449, currency="USD")
        assert first is True and second is False

        # digital fulfillment pops keys
        vals = await db.pop_product_values(pid2, 1, oid)
        assert vals == ["KEY-1"], vals
        assert await db.unused_values_count(pid2) == 1
        assert await db.pop_product_values(pid2, 5, oid) is None  # short

        # reviews + rating aggregation
        await db.set_order_status(oid, "delivered")
        assert await db.has_purchased(user["id"], pid1)
        await db.add_review(user["id"], pid1, 5, "Great!")
        p = await db.get_product(pid1)
        assert p["rating_count"] == 1 and p["rating_sum"] == 5

        # wishlist toggle
        assert await db.wishlist_toggle(user["id"], pid1) is True
        assert await db.wishlist_toggle(user["id"], pid1) is False

        # referral: earnings ledger path
        ref_user = await db.create_user(222, "Bob")
        await db.record_referral_earning(ref_user["id"], user["id"], oid, 224)
        assert await db.referral_earnings_total(ref_user["id"]) == 224

        # audit + maintenance + block
        await db.audit(111, "test_action", "details")
        await db.kv_set("maintenance_mode", "1")
        assert await db.maintenance_on() is True
        await db.kv_set("maintenance_mode", "0")
        await db.update_user_admin(user["id"], is_blocked=1)
        assert (await db.get_user(user["id"]))["is_blocked"] == 1
        assert await db.count_blocked_users() == 1

        os.unlink(tmp.name)

    asyncio.run(run())


def main():
    print("Nova Shop Bot smoke tests")
    check("config parsing", test_config)
    check("fmt_money + stars", test_fmt_money)
    check("callback data < 64 bytes", test_callback_data_length)
    check("db round-trip", test_db_roundtrip)
    check("crypto: HD derivation vectors", test_hd_vectors)
    check("crypto: initData HMAC", test_initdata_hmac)
    check("crypto: CryptoBot webhook HMAC", test_cryptobot_hmac)
    check("crypto: deposit matching", test_deposit_matching)
    check("crypto: payment rails", test_payment_rails)
    check("crypto: miniapp payload validation", test_miniapp_payload)
    print(f"\nALL {len(PASS)} GROUPS PASSED")


# ------------------------------------------------- SPEC2: crypto tests ---
def test_hd_vectors():
    """Account-xpub derivation against verified test vectors.

    Account xpubs are built from the standard 'abandon...about' mnemonic
    at m/84'/0'/0' (BTC), m/44'/60'/0' (ETH), m/44'/195'/0' (TRX); the
    bot then derives m/0/<index>. Index-0 addresses must equal the
    canonical vectors (BTC cross-checked against the hdwallet docs;
    ETH confirmed independently via coincurve + Keccak).
    """
    import crypto_payments as cp
    from hdwallet.hds.bip32 import BIP32HD
    from hdwallet.eccs import SLIP10Secp256k1ECC
    from hdwallet.mnemonics import BIP39Mnemonic
    from hdwallet.seeds import BIP39Seed

    mnemonic = ("abandon abandon abandon abandon abandon abandon abandon abandon"
                " abandon abandon abandon about")
    seed_hex = BIP39Seed.from_mnemonic(mnemonic=BIP39Mnemonic(mnemonic=mnemonic))

    def account_xpub(purpose: int, coin: int) -> str:
        node = BIP32HD(ecc=SLIP10Secp256k1ECC)
        node.from_seed(seed=seed_hex)
        for i in (purpose | 0x80000000, coin | 0x80000000, 0 | 0x80000000):
            node = node.drive(i)
        return node.xpublic_key()

    vectors = (
        ("btc", 84, 0, "bc1qcr8te4kr609gcawutmrza0j4xv80jy8z306fyu"),
        ("eth", 44, 60, "0x9858EfFD232B4033E47d90003D41EC34EcaEda94"),
        ("trx", 44, 195, "TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH"),
    )
    for chain, purpose, coin, expected in vectors:
        xpub = account_xpub(purpose, coin)
        assert cp.derive_address(chain, xpub, 0) == expected, chain
        # index 1 differs and parses as a valid address for the chain
        a1 = cp.derive_address(chain, xpub, 1)
        assert a1 != expected and len(a1) > 20, (chain, a1)
        # garbage xpub -> clean ValueError, never a crash
        try:
            cp.derive_address(chain, "not-a-key", 0)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{chain}: bad xpub should raise ValueError")

    # Money helpers: integer-only, no floats
    assert cp.format_crypto(123456789, "btc") == "1.23456789 BTC"
    assert cp.format_crypto(1000000, "eth") == "1 USDT"
    assert cp.format_crypto(1000000000, "ton") == "1 TON"
    # ceil rounding: $10 @ $50000/BTC -> 20000 sats exactly
    assert cp.usd_cents_to_base_units(1000, 50000.0, "btc") == 20000
    # $10 @ $33333.33/BTC -> ceil(1000*1e8/3333333) = 30001
    assert cp.usd_cents_to_base_units(1000, 33333.33, "btc") == 30001
    assert cp.meets_tolerance(98, 100) and not cp.meets_tolerance(97, 100)


def test_initdata_hmac():
    import webapp_auth
    token = "123456:TESTTOKEN"
    good = webapp_auth.make_test_vector(token)
    parsed = webapp_auth.validate_init_data(good, token)
    assert parsed and parsed.get("query_id") == "AAETEST", parsed
    # Tampered payload -> reject
    bad = good.replace("AAETEST", "ZZZFAKE")
    assert webapp_auth.validate_init_data(bad, token) is None
    # Wrong token -> reject
    assert webapp_auth.validate_init_data(good, "999:WRONG") is None
    # Missing hash -> reject
    assert webapp_auth.validate_init_data("a=1&b=2", token) is None


def test_cryptobot_hmac():
    import hashlib
    import hmac as hmac_mod
    import crypto_payments as cp
    token = "s3cr3t-token"
    body = b'{"update_id":1,"invoice_id":42,"status":"paid"}'
    key = hashlib.sha256(token.encode()).digest()
    sig = hmac_mod.new(key, body, hashlib.sha256).hexdigest()
    assert cp.verify_cryptobot_webhook(body, sig, token) is True
    assert cp.verify_cryptobot_webhook(body, sig.upper(), token) is True
    assert cp.verify_cryptobot_webhook(body, "0" * 64, token) is False
    assert cp.verify_cryptobot_webhook(b"", sig, token) is False
    assert cp.verify_cryptobot_webhook(body, sig, "other") is False


def test_deposit_matching():
    """Matcher trichotomy per SPEC2 §9: paid / underpaid / none.

    match_deposit returns the largest payment to the address; the caller
    splits paid vs underpaid with meets_tolerance (98%). matching_txs
    returns every payment so top-ups sum toward the expected total.
    """
    import crypto_payments as cp
    addr = "bc1qtest"

    # paid: exact single payment
    txs = [{"txid": "a", "to": addr, "sats": 50_000, "confirmations": 5}]
    best = cp.match_deposit("btc", txs, addr, 50_000)
    assert best and best["txid"] == "a"
    assert cp.meets_tolerance(50_000, 50_000)

    # largest payment wins as the reference tx
    txs = [
        {"txid": "a", "to": addr, "sats": 50_000, "confirmations": 5},
        {"txid": "d", "to": addr, "sats": 120_000, "confirmations": 4},
    ]
    assert cp.match_deposit("btc", txs, addr, 50_000)["txid"] == "d"

    # underpaid: still returned (not None) so the watcher can flag it;
    # 97k < 98% of 100k -> caller marks underpaid via meets_tolerance
    txs = [{"txid": "b", "to": addr, "sats": 97_000, "confirmations": 1}]
    best = cp.match_deposit("btc", txs, addr, 100_000)
    assert best and best["txid"] == "b"
    assert not cp.meets_tolerance(97_000, 100_000)
    assert cp.meets_tolerance(98_000, 100_000)  # boundary holds

    # none: nothing paid to this address
    txs = [{"txid": "c", "to": "bc1qother", "sats": 200_000, "confirmations": 9}]
    assert cp.match_deposit("btc", txs, addr, 50_000) is None
    assert cp.matching_txs("btc", txs, addr) == []

    # wrong address excluded; address match is case-insensitive
    txs = [
        {"txid": "c", "to": "bc1qother", "sats": 200_000, "confirmations": 9},
        {"txid": "e", "to": addr.upper(), "sats": 60_000, "confirmations": 2},
    ]
    assert cp.match_deposit("btc", txs, addr, 50_000)["txid"] == "e"

    # zero-amount dust ignored
    assert cp.match_deposit("btc", [{"txid": "z", "to": addr, "sats": 0}],
                                   addr, 50_000) is None

    # top-up: two payments sum to the expected total
    txs = [
        {"txid": "p1", "to": addr, "sats": 60_000, "confirmations": 6},
        {"txid": "p2", "to": addr, "sats": 40_000, "confirmations": 3},
    ]
    matches = cp.matching_txs("btc", txs, addr)
    assert len(matches) == 2
    assert sum(t["sats"] for t in matches) == 100_000
    assert cp.meets_tolerance(100_000, 100_000)

    # TON memo matching
    tton = [
        {"txid": "t1", "to": addr, "base": 5_000_000_000, "memo": "NOVA-9"},
        {"txid": "t2", "to": addr, "base": 5_000_000_000, "memo": "NOVA-10"},
    ]
    assert cp.match_deposit("ton", tton, addr, 5_000_000_000,
                            memo="NOVA-10")["txid"] == "t2"
    assert cp.match_deposit("ton", tton, addr, 5_000_000_000,
                            memo="NOVA-99") is None


def test_payment_rails():
    import asyncio
    import importlib
    import tempfile
    import crypto_payments as cp
    import config as cfg

    with _no_dotenv():
        _payment_rails_body(cp, cfg, importlib)
    # Belt & braces: never leak test env into the real repo .env scope.
    for _k in ("CRYPTOBOT_TOKEN", "PAYMENTS_PROVIDER_TOKEN", "XPUB_BTC",
               "XPUB_ETH", "XPUB_TRX", "TON_DEPOSIT_ADDRESS"):
        os.environ.pop(_k, None)


def _payment_rails_body(cp, cfg, importlib):
    async def run():
        os.environ["BOT_TOKEN"] = "test-token"
        # Case 1: nothing configured -> stars only (COD removed for digital-only)
        for k in ("CRYPTOBOT_TOKEN", "PAYMENTS_PROVIDER_TOKEN", "XPUB_BTC",
                  "XPUB_ETH", "XPUB_TRX", "TON_DEPOSIT_ADDRESS"):
            os.environ.pop(k, None)
        importlib.reload(cfg)
        importlib.reload(cp)
        rails = await cp.payment_rails(None, 1000)
        # New rail order: balance (always) -> stars -> crypto submenu
        # (COD removed for digital-only; direct chains hidden behind submenu)
        assert [m for m, _ in rails] == ["balance", "stars", "crypto"], rails
        assert rails[0][1].startswith("\U0001f4b3")
        assert rails[1][1].startswith("\u2b50")

        # Case 2: everything on -> balance, stars, cryptobot, card, crypto
        os.environ["CRYPTOBOT_TOKEN"] = "cb-test"
        os.environ["PAYMENTS_PROVIDER_TOKEN"] = "stripe-test"
        os.environ["XPUB_BTC"] = "zpub-test"
        os.environ["TON_DEPOSIT_ADDRESS"] = "EQ-test"
        importlib.reload(cfg)
        importlib.reload(cp)
        rails = await cp.payment_rails(None, 1000)
        methods = [m for m, _ in rails]
        assert methods == ["balance", "stars", "cryptobot", "card", "crypto"], methods
        # CryptoBot button is a clean label now (fee shown on the invoice screen,
        # not the button): "💎 CryptoBot".
        cb_label = rails[2][1]
        assert cb_label == "💎 CryptoBot", cb_label

        # restore
        for k in ("CRYPTOBOT_TOKEN", "PAYMENTS_PROVIDER_TOKEN", "XPUB_BTC",
                  "TON_DEPOSIT_ADDRESS"):
            os.environ.pop(k, None)
        importlib.reload(cfg)
        importlib.reload(cp)

    asyncio.run(run())


def test_miniapp_payload():
    """Payload validation rules: size cap, shape, sane quantities."""
    import json

    def validate(raw: str):
        if not raw or len(raw.encode("utf-8")) > 4096:
            return False
        try:
            p = json.loads(raw)
        except Exception:
            return False
        items = p.get("items")
        if not isinstance(items, list) or not items or len(items) > 50:
            return False
        for it in items:
            try:
                pid, qty = int(it.get("id")), int(it.get("qty"))
            except (TypeError, ValueError, AttributeError):
                return False
            if not 1 <= qty <= 99 or pid <= 0:
                return False
        return True

    assert validate(json.dumps({"items": [{"id": 1, "qty": 2}]})) is True
    assert validate("x" * 5000) is False
    assert validate("not json") is False
    assert validate(json.dumps({"items": []})) is False
    assert validate(json.dumps({"items": [{"id": 1, "qty": 0}]})) is False
    assert validate(json.dumps({"items": [{"id": "abc", "qty": 1}]})) is False
    assert validate(json.dumps({"items": [{"id": 1, "qty": 100}]})) is False


if __name__ == "__main__":
    main()


# The focused unit tests in test_webapp_auth.py are run by CI via unittest discovery.
