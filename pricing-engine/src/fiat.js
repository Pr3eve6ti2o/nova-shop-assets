/**
 * Fiat money math for the Nova Shop Payment & Pricing Engine.
 *
 * Built on Dinero.js v2, following the dinerojs/skills best practices:
 *  - amounts are ALWAYS integer minor units (cents) — never floats, never
 *    major units (rules: creation-minor-units, creation-from-floats);
 *  - Dinero objects are immutable: every helper returns a fresh value and
 *    callers use the return value (rule: arithmetic-immutability);
 *  - percentages use scaled amounts ({ amount, scale }), never raw decimal
 *    multipliers (rule: arithmetic-scaled-amounts);
 *  - splits use `allocate`, which distributes the remainder so no cent is
 *    created or destroyed (rule: arithmetic-allocate-not-divide).
 *
 * PARITY CONTRACT with the Python bot (the server-side authority):
 *  - subtotal        = sum(price_cents * qty)                (handlers/common.py)
 *  - percent promo   = floor(basis * pct / 100)              (database.validate_promo)
 *  - fixed promo     = value cents, clamped to the basis
 *  - discount        = min(discount, subtotal)               (common.totals)
 *  - total           = max(0, subtotal - discount + delivery_fee)
 *  - CryptoBot gross = ceil(net * 100 / (100 - fee_pct))     (handlers/crypto.py)
 * Percent discounts therefore scale DOWN (floor). Tax is the one place the
 * engine rounds half-up: the bot has no tax line today, so tax is an
 * engine-level policy for future use, documented in the README.
 */
import {
  dinero,
  add,
  subtract,
  multiply,
  allocate,
  transformScale,
  toSnapshot,
  toDecimal,
  down,
  halfUp,
  USD,
} from 'dinero.js';

export { USD };

function assertCents(value, name) {
  if (!Number.isSafeInteger(value)) {
    throw new TypeError(`${name} must be an integer number of cents, got ${value}`);
  }
}

/** Create a Dinero object from integer cents. The ONLY way money enters. */
export function money(cents, currency = USD) {
  assertCents(cents, 'cents');
  return dinero({ amount: cents, currency });
}

/** Integer cents back out of a Dinero object (scale must be the exponent). */
export function centsOf(dineroObject) {
  const snap = toSnapshot(dineroObject);
  if (snap.scale !== snap.currency.exponent) {
    throw new Error(`expected scale ${snap.currency.exponent}, got ${snap.scale} — trim/transform first`);
  }
  return snap.amount;
}

/** price * qty for one cart line, in cents. */
export function lineTotalCents(priceCents, qty, currency = USD) {
  if (!Number.isSafeInteger(qty) || qty < 0) {
    throw new TypeError(`qty must be a non-negative integer, got ${qty}`);
  }
  return centsOf(multiply(money(priceCents, currency), qty));
}

/** Sum of line totals for [{ priceCents, qty }], in cents. */
export function subtotalCents(items, currency = USD) {
  let acc = money(0, currency);
  for (const item of items) {
    acc = add(acc, money(lineTotalCents(item.priceCents, item.qty, currency), currency));
  }
  return centsOf(acc);
}

/**
 * pct% of a cent amount, rounded DOWN (floor) — the bot's promo rule:
 * discount = basis * pct // 100. Implemented as a Dinero scaled multiply
 * followed by transformScale(..., down); never float math.
 */
export function percentFloorCents(cents, pct, currency = USD) {
  if (!Number.isSafeInteger(pct) || pct < 0 || pct > 100) {
    throw new RangeError(`pct must be an integer 0..100, got ${pct}`);
  }
  const scaled = multiply(money(cents, currency), { amount: pct, scale: 2 });
  return centsOf(transformScale(scaled, currency.exponent, down));
}

/**
 * rate% of a cent amount, rounded HALF-UP — the engine's tax policy.
 * `ratePct` may carry up to 3 decimals (e.g. 8.875), passed as a scaled
 * amount so no float ever touches money.
 */
export function percentHalfUpCents(cents, ratePct, currency = USD) {
  const milliPct = Math.round(ratePct * 1000); // thousandths of a percent
  if (!Number.isFinite(ratePct) || ratePct < 0 || !Number.isSafeInteger(milliPct)) {
    throw new RangeError(`ratePct must be a non-negative number with <= 3 decimals, got ${ratePct}`);
  }
  const scaled = multiply(money(cents, currency), { amount: milliPct, scale: 5 });
  return centsOf(transformScale(scaled, currency.exponent, halfUp));
}

/**
 * CryptoBot-style gross-up: the provider deducts feePct% from the gross,
 * so the invoice must be ceil(net * 100 / (100 - feePct)). Returns
 * { grossCents, feeCents } with fee = gross - net (bot parity).
 */
export function grossUpCents(netCents, feePct, currency = USD) {
  if (!Number.isSafeInteger(feePct) || feePct < 0 || feePct >= 100) {
    throw new RangeError(`feePct must be an integer 0..99, got ${feePct}`);
  }
  if (feePct === 0) return { grossCents: netCents, feeCents: 0 };
  // Dinero has no rational division, so this one step uses the bot's exact
  // integer ceiling formula: ceil(net*100 / (100-feePct)). All operands are
  // safe integers; no float ever appears (the division result is floored
  // immediately and the numerator is pre-biased by (divisor - 1), which is
  // exact integer ceiling for safe-integer inputs).
  const gross = Math.floor((netCents * 100 + (100 - feePct) - 1) / (100 - feePct));
  return { grossCents: gross, feeCents: gross - netCents };
}

/**
 * Split a cent amount by integer ratios with `allocate`: the parts always
 * sum back to the original — no cent is lost or invented. Use for
 * platform/provider revenue splits.
 */
export function splitCents(cents, ratios, currency = USD) {
  if (!Array.isArray(ratios) || ratios.length === 0 ||
      ratios.some((r) => !Number.isSafeInteger(r) || r < 0) ||
      ratios.reduce((a, b) => a + b, 0) <= 0) {
    throw new RangeError('ratios must be non-negative integers with a positive sum');
  }
  return allocate(money(cents, currency), ratios).map(centsOf);
}

/** Subtract with a floor of zero (totals never go negative). */
export function subtractFloorZeroCents(aCents, bCents, currency = USD) {
  const out = centsOf(subtract(money(aCents, currency), money(bCents, currency)));
  return Math.max(0, out);
}

/**
 * Display formatting, per dinero-formatting skill: derive the decimal
 * string with toDecimal and format through Intl.NumberFormat.
 * Grouping is DISABLED so output is byte-identical to the bot's
 * fmt_money and the Mini App's previous money(): formatMoney(1999)
 * === '$19.99' and formatMoney(100000) === '$1000.00' (not '$1,000.00').
 * Prices in this shop never silently change their displayed shape.
 */
export function formatMoney(cents, currency = USD, locale = 'en-US') {
  const decimal = toDecimal(money(cents, currency), ({ value }) => value);
  const formatter = new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.code,
    useGrouping: false,
  });
  return formatter.format(decimal);
}
