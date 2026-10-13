/**
 * Cryptocurrency amounts for the Nova Shop Payment & Pricing Engine.
 *
 * Two tools, two jobs (per the project owner's structure):
 *  - Decimal.js does the rate conversion math. Exchange rates are decimal
 *    strings, and the conversion must be exact and deterministic — binary
 *    floats are never allowed near a quote.
 *  - Dinero.js with the BIGINT calculator models the resulting amounts as
 *    money objects with custom high-exponent currencies (dinero skill
 *    rule precision-crypto: 1 ETH = 10^18 wei overflows `number`).
 *
 * PARITY CONTRACT with the Python bot (crypto_payments.py, the authority):
 *    price_cents = ceil(Decimal(str(price_usd)) * 100)          (ROUND_CEILING)
 *    base_units  = ceil(usd_cents * 10^decimals / price_cents)
 * The shop rounds UP so a quote never under-charges. Asset keys, decimals
 * and symbols mirror bot/crypto_payments.py CHAINS exactly — note the bot
 * keys are NETWORKS: on "eth" and "trx" the deposit asset is USDT (6 dp).
 *
 * (File name follows the dinero skill guidance: never name a file after a
 * ticker code — ad blockers flag such files as crypto miners.)
 */
import Decimal from 'decimal.js';
import { dinero as dineroBig, toSnapshot } from 'dinero.js/bigint';

Decimal.set({ precision: 50 });

/** Mirrors bot/crypto_payments.py CHAINS (key = network). */
export const ASSETS = Object.freeze({
  btc:          { symbol: 'BTC',  decimals: 8 },
  eth:          { symbol: 'USDT', decimals: 6 },
  trx:          { symbol: 'USDT', decimals: 6 },
  ton:          { symbol: 'TON',  decimals: 9 },
  usdt_base:    { symbol: 'USDT', decimals: 6 },
  usdc_base:    { symbol: 'USDC', decimals: 6 },
  usdt_op:      { symbol: 'USDT', decimals: 6 },
  usdc_op:      { symbol: 'USDC', decimals: 6 },
  usdt_polygon: { symbol: 'USDT', decimals: 6 },
  usdc_polygon: { symbol: 'USDC', decimals: 6 },
});

function asset(assetKey) {
  const a = ASSETS[assetKey];
  if (!a) throw new RangeError(`unknown asset key: ${assetKey}`);
  return a;
}

/** Custom Dinero currency for an asset (bigint base/exponent). */
export function assetCurrency(assetKey) {
  const a = asset(assetKey);
  return { code: a.symbol, base: 10n, exponent: BigInt(a.decimals) };
}

/** A Dinero (bigint) money object holding integer base units. */
export function cryptoMoney(baseUnits, assetKey) {
  const units = typeof baseUnits === 'bigint' ? baseUnits : BigInt(baseUnits);
  if (units < 0n) throw new RangeError('baseUnits must be non-negative');
  return dineroBig({ amount: units, currency: assetCurrency(assetKey) });
}

/** Integer base units back out of a crypto Dinero object, as a string. */
export function baseUnitsOf(cryptoDineroObject) {
  return toSnapshot(cryptoDineroObject).amount.toString();
}

/**
 * USD cents -> integer base units for `assetKey` at `priceUsd` (USD per
 * whole coin/token, number or string). Returns a decimal STRING so values
 * beyond Number.MAX_SAFE_INTEGER (e.g. wei-scale) survive intact.
 * Byte-for-byte the bot's usd_cents_to_base_units.
 */
export function usdCentsToBaseUnits(usdCents, priceUsd, assetKey) {
  const a = asset(assetKey);
  if (!Number.isSafeInteger(usdCents) || usdCents < 0) {
    throw new TypeError(`usdCents must be a non-negative integer, got ${usdCents}`);
  }
  let price;
  try {
    price = new Decimal(String(priceUsd));
  } catch {
    throw new RangeError('bad price');
  }
  if (!price.isFinite() || price.lte(0)) throw new RangeError('bad price');
  const priceCents = price.mul(100).toDecimalPlaces(0, Decimal.ROUND_CEIL);
  if (priceCents.lte(0)) throw new RangeError('bad price');
  const units = new Decimal(usdCents)
    .mul(new Decimal(10).pow(a.decimals))
    .div(priceCents)
    .toDecimalPlaces(0, Decimal.ROUND_CEIL);
  return units.toString();
}

/** Convenience: USD cents -> nanotons string for a TON Connect transfer. */
export function usdCentsToTonNano(usdCents, tonPriceUsd) {
  return usdCentsToBaseUnits(usdCents, tonPriceUsd, 'ton');
}

/**
 * Integer base units -> human decimal string, mirroring the bot's
 * format_crypto: trailing fraction zeros trimmed, no float anywhere.
 * formatBaseUnits('1923076924', 'ton') === '1.923076924 TON'
 */
export function formatBaseUnits(baseUnits, assetKey) {
  const a = asset(assetKey);
  const units = BigInt(baseUnits);
  if (units < 0n) throw new RangeError('baseUnits must be non-negative');
  const base = 10n ** BigInt(a.decimals);
  const whole = units / base;
  const frac = units % base;
  if (frac === 0n) return `${whole} ${a.symbol}`;
  const fracStr = frac.toString().padStart(a.decimals, '0').replace(/0+$/, '');
  return `${whole}.${fracStr} ${a.symbol}`;
}

/**
 * Provider-format helper (dinero currency-patterns skill: dedicated
 * helpers per payment service). TON Connect expects the amount as a
 * nanoton decimal string — exactly what usdCentsToBaseUnits returns.
 */
export function toTonConnectAmount(usdCents, tonPriceUsd) {
  return usdCentsToTonNano(usdCents, tonPriceUsd);
}
