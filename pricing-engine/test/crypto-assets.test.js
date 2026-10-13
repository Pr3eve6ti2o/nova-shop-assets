/**
 * Crypto conversion parity. Every expected value below was produced by
 * the Python bot itself (crypto_payments.usd_cents_to_base_units /
 * format_crypto) — the JS engine must reproduce them exactly.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ASSETS,
  usdCentsToBaseUnits,
  usdCentsToTonNano,
  formatBaseUnits,
  cryptoMoney,
  baseUnitsOf,
} from '../src/index.js';

test('asset table mirrors bot CHAINS keys/decimals', () => {
  assert.equal(ASSETS.btc.decimals, 8);
  assert.equal(ASSETS.ton.decimals, 9);
  assert.equal(ASSETS.eth.decimals, 6); // network key: asset is USDT (ERC-20)
  assert.equal(ASSETS.trx.decimals, 6); // network key: asset is USDT (TRC-20)
  assert.equal(ASSETS.usdc_polygon.decimals, 6);
});

test('usdCentsToBaseUnits reproduces bot quotes exactly', () => {
  assert.equal(usdCentsToBaseUnits(2599, '67234.5', 'btc'), '38656');
  assert.equal(usdCentsToBaseUnits(1000, '5.20', 'ton'), '1923076924');
  assert.equal(usdCentsToBaseUnits(499, '3123.456', 'eth'), '1598');
  assert.equal(usdCentsToBaseUnits(10000, '1.0', 'trx'), '100000000');
  assert.equal(usdCentsToBaseUnits(12345, '0.998', 'usdt_base'), '123450000');
  assert.equal(usdCentsToBaseUnits(50, '150000', 'btc'), '334');
});

test('quotes round UP so the shop never under-receives (bot rule)', () => {
  // $0.01 of BTC at $150,000: exact = 6.66... sats -> 7, never 6.
  assert.equal(usdCentsToBaseUnits(1, '150000', 'btc'), '7');
  // Price with >2dp is ceiled to whole cents first (bot: price_cents ceil).
  assert.equal(usdCentsToBaseUnits(100, '0.001', 'ton'), usdCentsToBaseUnits(100, '0.01', 'ton'));
});

test('bad prices fail closed like the bot', () => {
  assert.throws(() => usdCentsToBaseUnits(100, '0', 'btc'), RangeError);
  assert.throws(() => usdCentsToBaseUnits(100, '-5', 'btc'), RangeError);
  assert.throws(() => usdCentsToBaseUnits(100, 'abc', 'btc'), RangeError);
  assert.throws(() => usdCentsToBaseUnits(100, '5', 'doge'), RangeError);
});

test('TON Connect nanoton amounts come from Decimal, not float division', () => {
  // The Mini App previously computed Math.round((usd/rate) * 1e9) in
  // binary floats. Exact: ceil(1000c * 1e9 / 520c) = 1923076924.
  assert.equal(usdCentsToTonNano(1000, '5.20'), '1923076924');
  assert.equal(usdCentsToTonNano(1000, 5.2), '1923076924'); // number input via String()
});

test('formatBaseUnits mirrors bot format_crypto', () => {
  assert.equal(formatBaseUnits('38656', 'btc'), '0.00038656 BTC');
  assert.equal(formatBaseUnits('1923076924', 'ton'), '1.923076924 TON');
  assert.equal(formatBaseUnits('100000000', 'trx'), '100 USDT');
  assert.equal(formatBaseUnits('123450000', 'usdt_base'), '123.45 USDT');
  assert.equal(formatBaseUnits('0', 'btc'), '0 BTC');
});

test('cryptoMoney round-trips base units through Dinero bigint', () => {
  const m = cryptoMoney('1923076924', 'ton');
  assert.equal(baseUnitsOf(m), '1923076924');
  assert.throws(() => cryptoMoney('-1', 'ton'), RangeError);
});
